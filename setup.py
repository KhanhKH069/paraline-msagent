from setuptools import setup, find_packages

setup(
    name='vietnamese-bert-vits2',
    version='1.0.0',
    description='Vietnamese Text-to-Speech with VITS2 + PhoBERT',
    author='Your Name',
    python_requires='>=3.10',
    packages=find_packages(),
    install_requires=[
        'torch>=2.0.0',
        'torchaudio>=2.0.0',
        'transformers>=4.35.0',
        'librosa>=0.10.0',
        'soundfile>=0.12.0',
        'numpy>=1.24.0',
        'num2words>=0.5.13',
    ],
)
