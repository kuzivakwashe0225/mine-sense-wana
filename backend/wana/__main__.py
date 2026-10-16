"""Command line: python -m wana <command>

  sample            write the synthetic SAMPLE dataset (for development only)
  ingest [--dry-run] [--only dem,s2,aster,mrds]
                    download the real open datasets for the pilot area
  stack             build the aligned evidence stack + evidence previews
  train             train a new model version from known occurrences + reviewed field records
  serve [--port N]  run the API and the built web app
  all-sample        sample -> stack -> train (quick start)
"""
import argparse
import json


def main():
    ap = argparse.ArgumentParser(prog="wana")
    ap.add_argument("cmd")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    if a.cmd in ("sample", "all-sample"):
        from .sample import generate
        print(json.dumps(generate()))
    if a.cmd == "ingest":
        from .ingest import run
        run(dry=a.dry_run, only=[s for s in a.only.split(",") if s] or None)
    if a.cmd in ("stack", "all-sample"):
        from .model import render_evidence
        from .stack import build
        m = build()
        render_evidence()
        print(json.dumps({k: m[k] for k in ("features", "occurrences", "any_sample")}))
    if a.cmd in ("train", "all-sample"):
        from .db import retrain_from_db
        m = retrain_from_db(note="Command-line training run")
        print(json.dumps({"version": m["version"], "metrics": {k: v for k, v in m["metrics"].items() if k != "curve"}}))
    if a.cmd == "serve":
        import uvicorn
        uvicorn.run("wana.api:app", host=a.host, port=a.port)


if __name__ == "__main__":
    main()
