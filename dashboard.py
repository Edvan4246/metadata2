from __future__ import annotations

import argparse
import logging

from flask import Flask, jsonify, render_template

from arbitrage_bot.config import Settings
from arbitrage_bot.dashboard_data import load_opportunities, load_trades, summarize_trades

logger = logging.getLogger(__name__)


def create_app(settings: Settings) -> Flask:
    """Read-only monitoring dashboard for your own bot instance.

    Reads `data/trades.csv` / `data/opportunities.csv` and serves them as
    charts/tables. There is no write endpoint, no authentication, and no
    concept of multiple users/investors -- it's a window into your own
    paper/live trading, nothing more. Do not expose this beyond localhost
    without adding authentication first.
    """
    app = Flask(__name__)

    @app.get("/")
    def index():
        return render_template("dashboard.html")

    @app.get("/api/summary")
    def api_summary():
        trades = load_trades(settings.logging.trades_log_path)
        return jsonify(summarize_trades(trades))

    @app.get("/api/trades")
    def api_trades():
        trades = load_trades(settings.logging.trades_log_path)
        return jsonify(list(reversed(trades[-50:])))

    @app.get("/api/opportunities")
    def api_opportunities():
        opportunities = load_opportunities(settings.logging.opportunities_log_path)
        return jsonify(list(reversed(opportunities[-50:])))

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Dashboard de monitoramento (somente leitura)")
    parser.add_argument("--config", default="config/settings.yaml", help="Caminho do arquivo de configuracao")
    parser.add_argument("--host", default="127.0.0.1", help="Endereco para o servidor escutar")
    parser.add_argument("--port", type=int, default=8000, help="Porta do servidor")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    settings = Settings.load(args.config)

    if args.host not in ("127.0.0.1", "localhost"):
        logger.warning(
            "Dashboard escutando em '%s' (nao localhost) sem autenticacao -- "
            "qualquer um na rede acessivel pode ver seus dados de trading.",
            args.host,
        )

    app = create_app(settings)
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
