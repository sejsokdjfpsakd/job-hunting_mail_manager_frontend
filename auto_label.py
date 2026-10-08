#!/usr/local/bin/python3.14
import bootstrap
import argparse
from rules import rules_store, run_rules_for_folder

def main():
    parser = argparse.ArgumentParser(description="Auto Label Cron Script")
    parser.add_argument("--dry-run", action="store_true", help="Do not move emails")
    parser.add_argument("--rule", type=str, help="Run specific rule ID only")
    args = parser.parse_args()
    
    def _read_rules(data):
        if args.rule:
            return [r for r in data if r["id"] == args.rule]
        return [r for r in data if r.get("is_active", True)]
        
    rules_to_run = rules_store.update(_read_rules)
    if not rules_to_run:
        print("No active rules to run.")
        return
        
    print(f"Running {len(rules_to_run)} rules... (dry_run={args.dry_run})")
    
    try:
        # Cron assumes we just run diffs on INBOX.
        # But wait, we might have paused full scans. 
        # rules.py handles paused scans automatically if we call it or we can just run INBOX for now.
        res = run_rules_for_folder("INBOX", rules_to_run, full_rescan=False, dry_run=args.dry_run)
        print(f"Matched {res['matched_count']} emails. Resumed scan: {res['resumed_full_scan']}.")
        if res.get('completed_scan'):
            print("A full scan was completed!")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
