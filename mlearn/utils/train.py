import torch
import numpy as np
from mlearn import base
from tqdm import tqdm, trange
from mlearn.utils.metrics import Metrics
from mlearn.utils.early_stopping import EarlyStopping
from mlearn.utils.pipeline import process_and_batch, vectorize
from mlearn.data.fileio import write_predictions, write_results
from mlearn.utils.evaluate import eval_torch_model, eval_sklearn_model
from sklearn.model_selection import KFold, StratifiedKFold, GridSearchCV


def run_singletask_model(library: str, train: bool, writer: base.Callable, model_info: list, head_len: int, **kwargs):
    """
    Train or evaluate model.

    :library (str): Library of the model.
    :train (bool): Whether it's a train or test run.
    :writer (csv.writer): File to output model performance to.
    :model_info (list): Information about the model to be added to each line of the output.
    :head_len (int): The length of the header.
    """
    if train:
        func = train_singletask_model if library == 'pytorch' else select_sklearn_training_regiment
    else:
        func = eval_torch_model if library == 'pytorch' else eval_sklearn_model

    train_loss, dev_loss, train_scores, dev_scores = func(**kwargs)
    write_results(writer, train_scores, train_loss, dev_scores, dev_loss, model_info = model_info, exp_len = head_len,
                  **kwargs)

    if not train:
        write_predictions(kwargs['test_obj'], model_info = model_info, **kwargs)


def _singletask_epoch(model: base.ModelType, optimizer: base.Callable, loss_func: base.Callable,
                      iterator: base.DataType, clip: float = None, gpu: bool = True, **kwargs):
    """
    Training procedure for single task pytorch models.

    :model (base.ModelType): Untrained model to be trained.
    :optimizer (bas.Callable): Optimizer function.
    :loss_func (base.Callable): Loss function to use.
    :iterator (base.DataType): Batched training set.
    :clip (float, default = None): Add gradient clipping to prevent exploding gradients.
    :gpu (bool, default = True): Run on GPU
    :returns: TODO
    """
    with tqdm(iterator, desc = "Batch", leave = False) as loop:
        predictions, labels = [], []
        epoch_loss = 0

        for X, y in loop:
            if gpu:
                X = X.cuda()
                y = y.cuda()

            scores = model(X, **kwargs)
            loss = loss_func(scores, y)
            loss.backward()

            if clip is not None:
                torch.nn.utils.clip_grad_norm(model.parameters(), clip)

            optimizer.step()

            predictions.extend(torch.argmax(scores, 1).cpu().tolist())
            labels.extend(y.cpu().tolist())
            epoch_loss += loss.data.item()
            batch_loss = loss.data.item() / len(y)

            loop.set_postfix(batch_loss = f"{batch_loss:.4f}",
                             epoch_loss = f"{epoch_loss / len(labels):.4f}")

    return predictions, labels, epoch_loss / len(labels)


def train_singletask_model(model: base.ModelType, save_path: str, epochs: int, iterator: base.DataType,
                           loss_func: base.Callable, optimizer: base.Callable, metrics: object,
                           dev_iterator: base.DataType = None, dev_metrics: object = None, clip: float = None,
                           patience: int = 10, low_is_good: bool = False, shuffle: bool = True, gpu: bool = True,
                           **kwargs) -> base.Union[list, int, dict, dict]:
    """
    Train a single task pytorch model.

    :model (base.ModelType): Untrained model to be trained.
    :save_path (str): Path to save models to.
    :epochs (int): The number of epochs to run.
    :iterator (base.DataType): Batched training set.
    :loss_func (base.Callable): Loss function to use.
    :optimizer (bas.Callable): Optimizer function.
    :metrics (object): Initialized Metrics object.
    :dev_iterator (base.DataType, optional): Batched dev set.
    :dev_metrics (object): Initialized Metrics object.
    :clip (float, default = None): Clip gradients to prevent exploding gradient problem.
    :patience (int, default = 10): Number of iterations to keep going before early stopping.
    :low_is_good (bool, default = False): Lower scores indicate better performance.
    :shuffle (bool, default = True): Shuffle the dataset.
    :gpu (bool, default = True): Run on GPU
    """
    with trange(epochs, desc = "Training epochs", leave = False) as loop:
        preds, labels = [], []

        if patience > 0:
            early_stopping = EarlyStopping(save_path, model, patience, low_is_good = low_is_good)

        for ep in loop:
            model.train()
            optimizer.zero_grad()  # Zero out gradients

            if shuffle:
                iterator.shuffle()

            epoch_preds, epoch_labels, epoch_loss = _singletask_epoch(model, optimizer, loss_func, iterator, clip, gpu)

            preds.extend(epoch_preds)
            labels.extend(epoch_labels)
            metrics.compute(epoch_labels, epoch_preds)
            metrics.loss(epoch_loss)

            try:
                dev_loss, _, _, _ = eval_torch_model(model, dev_iterator, loss_func, dev_metrics, gpu, store = False,
                                                     **kwargs)
                dev_metrics.loss(dev_loss)
                dev_score = dev_metrics[dev_metrics.display_metric][-1]

                if early_stopping is not None and early_stopping(model, dev_metrics.early_stopping()):
                    model = early_stopping.best_state
                    break

                loop.set_postfix(epoch_loss = f"{epoch_loss:.4f}",
                                 dev_loss = f"{dev_loss:.4f}",
                                 **metrics.display(),
                                 dev_score = dev_score)
            except Exception:
                loop.set_postfix(epoch_loss = f"{epoch_loss:.4f}", **metrics.display())
            finally:
                loop.refresh()

    return metrics.scores['loss'], dev_metrics.scores['dev_loss'], metrics.scores, dev_metrics.scores


def run_mtl_model(library: str, train: bool, writer: base.Callable, model_info: list, head_len: int, **kwargs):
    """
    Train or evaluate model.

    :library (str): Library of the model.
    :train (bool): Whether it's a train or test run.
    :writer (csv.writer): File to output model performance to.
    :model_info (list): Information about the model to be added to each line of the output.
    :head_len (int): The length of the header.
    """
    if train:
        func = train_mtl_model if library == 'pytorch' else select_sklearn_training_regiment
    else:
        func = eval_torch_model if library == 'pytorch' else eval_sklearn_model

    train_loss, dev_loss, train_scores, dev_scores = func(**kwargs)
    write_results(writer, train_scores, train_loss, dev_scores, dev_loss, model_info = model_info, exp_len = head_len,
                  **kwargs)

    if not train:
        write_predictions(kwargs['test_obj'], model_info = model_info, **kwargs)


def _mtl_epoch(model: base.ModelType, loss_func: base.Callable, loss_weights: base.DataType, opt: base.Callable,
               metrics: object, batchers: base.List[base.Batch], batch_count: int, dataset_weights: base.List[float],
               clip: float = None, **kwargs):
    """
    Train one epoch of an MTL training loop.

    :model (base.ModelType): Model in the process of being trained.
    :loss_func (base.Callable): The loss function being used.
    :loss_weights (base.DataType): Determines relative task importance When using multiple input/output functions.
    :opt (base.Callable): The optimizer function used.
    :metrics (object): Initialized Metrics object.
    :batchers (base.List[base.Batch]): A list of batched objects.
    :batch_count (int): The number of batches to go through in each epoch.
    :dataset_weights (base.List[float]): The probability with which each dataset is chosen to be trained on.
    :clip (float, default = None): Use gradient clipping.
    """
    with tqdm(range(batch_count, desc = 'Batch', leave = False)) as loop:
        label_count = 0
        epoch_loss = 0

        for b in loop:

            # Select task and get batch
            task_id = np.random.choice(range(len(batchers)), p = dataset_weights)
            X, y = next(iter(batchers[task_id]))

            # Do model training
            model.train()
            opt.zero_grad()

            scores = model(X, task_id, **kwargs)
            loss = loss_func(scores, y) * loss_weights[task_id]
            loss.backwards()

            if clip is not None:
                torch.nn.utils.clip_grad_norm(model.parameters(), clip)  # Prevent exploding gradients

            opt.step()

            metrics.compute(scores, y)
            label_count += len(y.cpu().tolist())
            epoch_loss += loss.data.item().cpu()
            batch_loss = loss.data.item().cpu() / len(y)

            loop.set_postfix(batch_loss = f"{batch_loss:.4f}",
                             epoch_loss = f"{epoch_loss / label_count:.4f}",
                             **metrics.display(),
                             task = task_id)

    return epoch_loss / label_count


def train_mtl_model(model: base.ModelType, training_datasets: base.List[base.DataType], save_path: str,
                    opt: base.Callable, loss_func: base.Callable, metrics: object, batch_size: int = 64,
                    epochs: int = 2, clip: float = None, patience: int = 10, dev: base.DataType = None,
                    dev_task_id: int = 0, batches_per_epoch: int = None, shuffle_data: bool = True,
                    dataset_weights: base.DataType = None, loss_weights: base.DataType = None, **kwargs) -> None:
    """
    Train a multi-task learning model.

    :model (base.ModelType): Untrained model.
    :training_datasets (base.List[base.DataType]): List of tuples containing dense matrices.
    :save_path (str): Path to save trained model to.
    :opt (base.Callable): Pytorch optimizer to train model.
    :loss_func (base.Callable): Loss function.
    :metrics (object): Initialized metrics object.
    :batch_size (int): Training batch size.
    :epochs (int): Maximum number of epochs (if no early stopping).
    :clip (float, default = None): Use gradient clipping.
    :patience (int, default = 10): Number of epochs to observe non-improving dev performance before early stopping.
    :dev (base.DataType): Dev dataset object.
    :dev_task_id (int, default = 0): Task ID for task to use for early stopping, in case of multitask learning.
    :batches_per_epoch (int, default = None): Set number of batches per epoch. If None, an epoch consists of all
                                              training examples.
    :shuffle_data: Whether to shuffle data at training.
    :dataset_weights (base.DataType, default = None): Probability for each dataset to be chosen (must sum to 1.0).
    :loss_weights (base.DataType): Determines relative task importance When using multiple input/output functions.
    """
    if loss_weights is None:
        loss_weights = np.ones(len(training_datasets))

    if dataset_weights is None:
        dataset_weights = loss_weights / len(training_datasets)

    if batches_per_epoch is None:
        batches_per_epoch = sum([len(dataset) * batch_size for dataset in training_datasets]) // batch_size

    if patience > 0:
        early_stopping = EarlyStopping(save_path, model, patience, low_is_good = False)

    batchers = []

    for train_data in training_datasets:
        batches = process_and_batch(train_data, train_data.data, batch_size, 'label')

        if shuffle_data:
            batches.shuffle()

        batchers.append(batches)

    with trange(epochs, desc = "Training model") as loop:
        dev_scores = []
        dev_losses = []
        train_loss = []

        for epoch in loop:
            epoch_loss = _mtl_epoch(model, loss_func, loss_weights, opt, batchers, batches_per_epoch,
                                                     dataset_weights, clip)
            train_loss.append(epoch_loss)

            try:
                dev_batches = process_and_batch(dev, dev.dev, len(dev.dev))
                dev_loss, _, dev_score, _ = eval_torch_model(model, dev_batches, loss_func,
                                                              metrics, mtl = True,
                                                              task_id = dev_task_id)
                dev_losses.append(dev_loss)
                dev_scores.append(dev_score)

                loop.set_postfix(loss = f"{epoch_loss:.4f}",
                                 dev_loss = f"{dev_loss:.4f}",
                                 dev_score = dev_score)

                if early_stopping is not None and early_stopping(model, dev_scores.early_stopping()):
                    model = early_stopping.get_best_state
                    break

            except Exception:
                loop.set_postfix(epoch_loss = epoch_loss)
            finally:
                loop.refresh()
    return train_loss, dev_losses, _, dev_scores


def train_sklearn_cv_model(model: base.ModelType, vectorizer: base.VectType, dataset: base.DataType,
                           cross_validate: int = None, stratified: bool = True, metrics: Metrics = None,
                           dev: base.DataType = None, dev_metrics: Metrics = None, **kwargs
                           ) -> base.Tuple[Metrics, Metrics]:
    """
    Train sklearn cv model.

    :model (base.ModelType): An untrained scikit-learn model.
    :vectorizer (base.VectType): An unfitted vectorizer.
    :dataset (GeneralDataset): The dataset object containing the training set.
    :cross_validate (int, default = None): The number of folds for cross-validation.
    :stratified (bool, default = True): Stratify data across the folds.
    :metrics (Metrics, default = None): An initialized metrics object.
    :dev (base.DataType, default = None): The development data.
    :dev_metrcs (Metrics, default = None): An initialized metrics object for the dev data.
    :returns (model, metrics, dev_metrics): Returns trained model object, metrics and dev_metrics objects.
    """
    # Load data
    train = vectorize(dataset.train, dataset, vectorizer)
    labels = [doc.label for doc in dataset.train]

    if stratified:
        folds = StratifiedKFold(cross_validate)
    else:
        folds = KFold(cross_validate)

    with trange(folds, desc = "Training model") as loop:
        for train_idx, test_idx in folds.split(train, labels):
            trainX, trainY = train[train_idx], labels[train_idx]
            testX, testY = train[test_idx], labels[test_idx]

            model.fit(trainX, trainY)
            eval_sklearn_model(model, testX, metrics, testY)

        try:
            devX = vectorize(dev, dataset, vectorizer)
            devY = [getattr(doc, getattr(f, 'name')) for f in dataset.label_fields for doc in dev]
            eval_sklearn_model(model, devX, dev_metrics, devY)

            loop.set_postfix(**metrics.display(), **dev_metrics.display())
        except Exception:
            loop.set_postfix(**metrics.display())
        finally:
            loop.refresh()

    return model, metrics, dev_metrics


def train_sklearn_gridsearch_model(model: base.ModelType, vectorizer: base.VectType, dataset: base.DataType,
                                   grid_search: dict, cross_validate: int = None, metrics: Metrics = None,
                                   dev: base.DataType = None, dev_metrics: Metrics = None, scoring: str = 'f1_weighted',
                                   n_jobs: int = -1, **kwargs) -> base.Tuple[base.ModelType, Metrics, Metrics]:
    """
    Train sklearn model using grid-search.

    :model (base.ModelType): An untrained scikit-learn model.
    :vectorizer (base.VectType): An unfitted vectorizer.
    :dataset (base.DataType): The dataset object containing train data.
    :grid_search (dict): The parameter grid to explore.
    :cross_validate (int, default = None): The number of folds for cross-validation.
    :metrics (Metrics, default = None): An initialized metrics object.
    :dev (base.DataType, default = None): The development data.
    :dev_metrcs (Metrics, default = None): An initialized metrics object for the dev data.
    :scoring (str, default = 'f1_weighted'): The scoring metrics used to define best functioning model.
    :n_jobs (int, default = -1): The number of processors to use (-1 == all processors).
    :returns (model, metrics, dev_metrics): Returns grid-search object, metrics and dev_metrics objects.
    """
    train = vectorize(dataset.train, dataset, vectorizer)
    labels = [doc.label for doc in dataset.train]

    with trange(1, desc = "Training model") as loop:
        model = GridSearchCV(model, grid_search, scoring, n_jobs = n_jobs, cv = cross_validate, refit = True)
        model.fit(train, labels)

        try:
            devX = vectorize(dev, dataset, vectorizer)
            devY = [getattr(doc, getattr(f, 'name')) for f in dataset.label_fields for doc in dev]
            eval_sklearn_model(model, devX, dev_metrics, devY)

            loop.set_postfix(f1_score = model.best_score_, **dev_metrics.display())
        except Exception:
            loop.set_postfix(f1_score = model.best_score_)
        finally:
            loop.refresh()

    return model, metrics, dev_metrics


def train_sklearn_model(model: base.ModelType, vectorizer: base.VectType, dataset: base.DataType, metrics: Metrics,
                        dev: base.DataType = None, dev_metrics: Metrics = None, **kwargs):
    """
    Train bare sci-kit learn model.

    :model (base.ModelType): An untrained scikit-learn model.
    :vectorizer (base.VectType): An unfitted vectorizer.
    :dataset (base.DataType): The dataset object containing train data.
    :grid_search (dict): The parameter grid to explore.
    :cross_validate (int, default = None): The number of folds for cross-validation.
    :metrics (Metrics, default = None): An initialized metrics object.
    :dev (base.DataType, default = None): The development data.
    :dev_metrcs (Metrics, default = None): An initialized metrics object for the dev data.
    :returns (model, metrics, dev_metrics): Returns trained model object, metrics and dev_metrics objects.
    """
    with trange(1, desc = "Training model") as loop:
        trainX = vectorize(dataset.train, dataset, vectorizer)
        trainY = [doc.label for doc in dataset.train]

        model.fit(trainX, trainY)

        try:
            devX = vectorize(dev, dataset, vectorizer)
            devY = [getattr(doc, getattr(f, 'name')) for f in dataset.label_fields for doc in dev]
            eval_sklearn_model(model, devX, dev_metrics, devY)

            loop.set_postfix(**metrics.display(), **dev_metrics.display())
        except Exception:
            loop.set_postfix(**metrics.display())
        finally:
            loop.refresh()

    return model, metrics, dev_metrics


def select_sklearn_training_regiment(model: base.ModelType, cross_validate: int = None, grid_search: dict = None,
                                     **kwargs):
    """
    Select the type of sklearn training regime.

    :model (base.ModelType): The model to be trained.
    :cross_validate (int, default = None): The number of folds to use for cross validation.
    :grid_search (dict, default = None): The parameters to search over.
    """
    if grid_search is not None:
        train_sklearn_gridsearch_model(model, cross_validate = cross_validate, grid_search = grid_search, **kwargs)
    elif cross_validate is not None:
        train_sklearn_cv_model(model, cross_validate = cross_validate, **kwargs)
    else:
        train_sklearn_model(**kwargs)
