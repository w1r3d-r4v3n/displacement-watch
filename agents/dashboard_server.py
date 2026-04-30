from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import db as dbmod
from .dashboard_data import (
    build_export_csv_bytes,
    build_share_bundle_bytes,
    get_briefs,
    get_country_detail,
    get_country_summary,
    get_displacement_flows,
    get_filter_options,
    get_map_points,
    get_overview,
    get_timeseries,
)


def _asset_root() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")


def run_dashboard_server(db_path: str = dbmod.DB_PATH, host: str = "127.0.0.1", port: int = 8765) -> None:
    asset_root = _asset_root()

    class DashboardHandler(BaseHTTPRequestHandler):
        def _send_json(self, payload: dict, status: int = 200) -> None:
            raw = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _send_file(self, path: str, content_type: str) -> None:
            with open(path, "rb") as f:
                raw = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _send_bytes(self, raw: bytes, content_type: str, filename: str | None = None) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(raw)

        def _query_params(self) -> dict[str, str | None]:
            query = parse_qs(urlparse(self.path).query)
            return {k: (v[0] if v else None) for k, v in query.items()}

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            params = self._query_params()
            route = parsed.path

            if route in ("/", "/dashboard") or route.startswith("/country/"):
                return self._send_file(os.path.join(asset_root, "dashboard.html"), "text/html; charset=utf-8")
            if route == "/static/app.js":
                return self._send_file(os.path.join(asset_root, "app.js"), "application/javascript; charset=utf-8")
            if route == "/static/app.css":
                return self._send_file(os.path.join(asset_root, "app.css"), "text/css; charset=utf-8")
            if route == "/api/filters":
                return self._send_json(get_filter_options(db_path))
            if route == "/api/overview":
                return self._send_json(
                    get_overview(
                        db_path,
                        country=params.get("country"),
                        event_type=params.get("event_type"),
                        population_type=params.get("population_type"),
                        signal=params.get("signal"),
                        start=params.get("start"),
                        end=params.get("end"),
                    )
                )
            if route == "/api/countries":
                return self._send_json(
                    {"countries": get_country_summary(
                        db_path,
                        country=params.get("country"),
                        event_type=params.get("event_type"),
                        population_type=params.get("population_type"),
                        signal=params.get("signal"),
                        start=params.get("start"),
                        end=params.get("end"),
                    )}
                )
            if route == "/api/country-detail":
                country = params.get("country")
                if not country:
                    return self._send_json({"error": "country is required"}, status=HTTPStatus.BAD_REQUEST)
                return self._send_json(get_country_detail(db_path, country))
            if route == "/api/timeseries":
                return self._send_json(
                    get_timeseries(db_path, country=params.get("country"), start=params.get("start"), end=params.get("end"))
                )
            if route == "/api/map":
                return self._send_json(get_map_points(db_path, start=params.get("start"), end=params.get("end")))
            if route == "/api/displacement":
                return self._send_json(get_displacement_flows(db_path))
            if route == "/api/briefs":
                return self._send_json(get_briefs(db_path, date=params.get("date")))
            if route == "/export/items.csv":
                raw = build_export_csv_bytes(
                    db_path,
                    country=params.get("country"),
                    start=params.get("start"),
                    end=params.get("end"),
                )
                return self._send_bytes(raw, "text/csv; charset=utf-8", "displacement-monitor-items.csv")
            if route == "/export/share-bundle.zip":
                raw = build_share_bundle_bytes(
                    db_path,
                    country=params.get("country"),
                    event_type=params.get("event_type"),
                    population_type=params.get("population_type"),
                    signal=params.get("signal"),
                    start=params.get("start"),
                    end=params.get("end"),
                )
                return self._send_bytes(raw, "application/zip", "displacement-monitor-share-bundle.zip")

            self._send_json({"error": "Not found", "path": route}, status=HTTPStatus.NOT_FOUND)

        def log_message(self, fmt: str, *args: object) -> None:
            print(f"[dashboard] {self.address_string()} - {fmt % args}")

    server = ThreadingHTTPServer((host, port), DashboardHandler)
    print(f"Displacement Monitor dashboard running at http://{host}:{port}/dashboard")
    print(f"Using database: {db_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
