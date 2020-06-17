import torch
from tqdm import tqdm
from mlearn import base
from mlearn.utils import metrics


def predict_torch_model(model: base.ModelType, iterator: base.DataType, loss_func: base.Callable, gpu: bool,
                        **kwargs) -> base.Tuple[list, list, float]:
    """
    Predict using trained model.

    :model (base.ModelType): Trained model to be trained.
    :iterator (base.DataType): Batched dataset to predict on.
    :loss_func (base.Callable): Loss function.
    :gpu (bool): True if run on GPU else false.
    :returns (base.Tuple[list, list, float]): Predictions, true labels, mean loss.
    """
    # TODO Modify this so it ONLY does the predictions and nothing else.
    predicted, labels = [], []
    loss = []

    for X, y in tqdm(iterator, desc = "Evaluating model", leave = False):
        if gpu:
            X = X.cuda()

        pred = model(X, **kwargs).cpu()
        li = loss_func(pred, y.cpu())
        loss.append(li.data.item())

        predicted.extend(torch.argmax(pred, dim = 1).tolist())
        labels.extend(y.cpu().tolist())

    return list(predicted), list(labels), torch.sum(torch.Tensor(loss)).item()


def eval_torch_model(model: base.ModelType, iterator: base.DataType, loss_func: base.Callable,
                     metrics: object, gpu: bool, mtl: bool = False, task_id: int = None,
                     store: bool = True, test_obj: base.DataType = None, **kwargs):
    """
    Evalute pytorch model.

    :model (base.ModelType): Trained model to be trained.
    :iterator (base.DataType): Batched dataset to predict on.
    :loss_func (base.Callable): Loss function.
    :metrics (object): Initialized Metrics object.
    :gpu (bool): True if running on a GPU else false.
    :mtl (bool, default = False): Is it a Multi-task Learning problem?
    :task_id (int, default = None): Task ID for MTL problem.
    :store (bool, default = True): Store the prediction if true.
    :test_obj (base.DataType, default = None): Data object to test on.
    :returns: TODO
    """
    with torch.no_grad():
        model.eval()

        if mtl and task_id is not None:
            predicted, true, loss = predict_torch_model(model, iterator, loss_func, gpu, task_id = task_id)
        else:
            predicted, true, loss = predict_torch_model(model, iterator, loss_func, gpu)

        if store:
            for doc, pred in zip(test_obj, predicted):
                setattr(doc, 'pred', pred)

        metrics.compute(true, predicted)

    return loss / len(true), None, metrics.scores, None


def predict_sklearn_model(model: base.ModelType, iterator: base.DataType, metrics: metrics.Metrics = None,
                          labels: base.DataType = None) -> base.Tuple[base.DataType, metrics.Metrics]:
    """
    Predict using trained Scikit-learn model.

    :model (base.ModelType): Trained model to be trained.
    :iterator (base.DataType): Dataset to predict on.
    :metrics (metrics.Metrics, default = None): Initialized Metrics object.
    :labels (base.DataType, default = None): For applying hte data
    :returns (Metrics.metrics): Metrics
    """
    preds = model.predict(iterator)
    if labels:
        metrics.compute(labels, preds)
    return preds, metrics


def eval_sklearn_model(model: base.ModelType, iterator: base.DataType, metrics: metrics.Metrics, labels: base.DataType,
                       store: bool = True, evalset: base.DataType = None):
    """
    Evaluate Scikit-learn model.

    :model (base.ModelType): Trained model to be trained.
    :iterator (base.DataType): Dataset to predict on.
    :metrics (object): Initialized Metrics object.
    :evalset (base.DataType): Data object being predicted on.
    :store (bool, default = True): Store the prediction if true.
    :returns (metrics.Metrics): Return evaluation metrics.
    """
    preds, metrics = predict_sklearn_model(model, iterator, metrics, labels)
    if store:
        for doc, lab, pred in zip(evalset, labels, preds):
            setattr(doc, 'pred', pred)


""" Joachim's Code, including regression evaluation.


def eval_model(model, X, y_true, task_id=0, batch_size=64):
    if model.binary:
        return eval_model_binary(model, X, y_true, task_id=task_id,
                                 batch_size=batch_size)
    else:
        return eval_model_regression(model, X, y_true, task_id=task_id,
                                     batch_size=batch_size)


def eval_model_regression(model, X, y_true, task_id=0, batch_size=64):
    predicted = predict_model(model, X, task_id, batch_size)
    mae, rank_corr = 0, float('nan')
    mae = mean_absolute_error(y_true, predicted)
    if predicted.sum() > 0:
        rank_corr = spearmanr(y_true, predicted)[0]
    return mae, rank_corr, predicted


def eval_model_binary(model, X, y_true, task_id=0, batch_size=64):
    predicted = predict_model(model, X, task_id, batch_size)
    f1 = f1_score(y_true, predicted)
    if predicted.sum() > 0:
        rank_corr = spearmanr(y_true, predicted)[0]
    else:
        rank_corr = float('nan')
    return f1, rank_corr, predicted
"""
