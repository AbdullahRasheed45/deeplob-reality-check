.PHONY: install test lint fi2010-download fi2010-train crypto-dataset train-baselines train-deeplob backtest report

install:
	pip install -e ".[dev]"

test:
	pytest

lint:
	ruff check .

fi2010-download:
	lobrc fi2010-download --config configs/fi2010.yaml

fi2010-train:
	lobrc fi2010-train --config configs/fi2010.yaml

crypto-dataset:
	lobrc crypto-dataset --config configs/crypto_dataset.yaml

train-baselines:
	lobrc train-baselines --config configs/baselines.yaml

train-deeplob:
	lobrc train-deeplob --config configs/crypto_deeplob.yaml

backtest:
	lobrc backtest --config configs/backtest.yaml

report:
	lobrc report --config configs/live.yaml
