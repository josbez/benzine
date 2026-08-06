.PHONY: install test build backtest forecast all demo serve clean

PY ?= python3
export PYTHONPATH := src

install:
	$(PY) -m pip install -r requirements.txt

test:
	$(PY) -m pytest tests/ -q

# Live run: fetches CBS, market data and today's advisory price.
build:
	$(PY) -m benzine build --source live

backtest:
	$(PY) -m benzine backtest --source live

forecast:
	$(PY) -m benzine forecast --source live

all:
	$(PY) -m benzine all --source live

# Offline end-to-end run on synthetic data -- verifies the pipeline, and
# produces a forecast.json the web app can render. Not real prices.
demo:
	$(PY) -m benzine all --source synthetic --refit-every 60

# Record today's advisory price. Run this daily (cron) to grow the GLA
# history that the same-day anchor depends on.
snapshot:
	$(PY) -c "from benzine.sources import gla; print(gla.record_today())"

serve:
	@echo "http://localhost:8000"
	@cd web && $(PY) -m http.server 8000

clean:
	rm -rf data/raw/*.parquet data/processed/*.parquet web/forecast.json
