import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name = "Mlearn",
    version = "0.0.1",
    author = "Zeerak Waseem",
    author_email = "zeerak.w@gmail.com",
    decription = "A package to contain machine learning pipelines for python.",
    long_description = long_description,
    long_description_content_type = "text/markdown",
    url="https://github.com/zeerakw/mlearn",
    packages = setuptools.find_packages(),
    classifiers=[
        "Programming Languge :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: Unix"
    ],
    python_requires='>3.6',
)
