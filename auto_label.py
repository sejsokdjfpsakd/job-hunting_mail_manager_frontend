#!/usr/bin/env python3
import bootstrap
import argparse
import sys
from imap_client import open_session, MailError
from rules import run_rules


def main():
    parser = argparse.ArgumentParser(description="Auto Label Cron Script")
    parser.add_argument("--dry-run", action="store_true", help="Do not move emails")
    parser.add_argument("--rule", type=str, help="Run specific rule ID only")
    args = parser.parse_args()

    try:
        with open_session() as session:
            res = run_rules(session, rule_id=args.rule, dry_run=args.dry_run)
            total_moved = res.get("total_moved", 0)
            print(f"Auto-label completed (dry_run={res.get('dry_run', False)}). Total moved: {total_moved}")
            for r in res.get("results", []):
                err = f" (Error: {r['error']})" if r.get("error") else ""
                inc = " [Incomplete]" if r.get("incomplete") else ""
                print(f"  - [{r['rule_id']}] {r['name']} ({r['mode']}): moved {r['moved']}{err}{inc}")
            if res.get("incomplete"):
                print("Notice: Execution reached time budget and will resume on next run.")
            if res.get("disabled_rules"):
                for d in res["disabled_rules"]:
                    print(f"  - Skipped [{d['id']}] {d['name']}: {d['reason']}")
    except MailError as e:
        if e.code == "busy":
            print(f"Notice: {e.message} (Skipped).")
            sys.exit(0)
        print(f"Mail error: {e.message} ({e.code})", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

