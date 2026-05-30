.PHONY: install run test backtest lint

install:
	pip install -r requirements.txt

run:
	python -m api.main

test:
	pytest tests/ -v --tb=short

backtest:
	python scripts/run_backtest.py

lint:
	python -m py_compile config/settings.py core/mt5_client.py core/data_fetcher.py \
	    strategy/indicators.py strategy/ml_model.py strategy/signal_generator.py \
	    risk/risk_manager.py risk/position_sizing.py \
	    execution/order_manager.py bot/trading_bot.py api/main.py
	@echo "Syntax OK"
