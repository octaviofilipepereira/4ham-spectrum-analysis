# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)

import argparse
import json
import urllib.request


def _post_json(url, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return resp.read().decode("utf-8")


def main():
    parser = argparse.ArgumentParser(description="4ham backend CLI")
    parser.add_argument("--host", default="http://localhost:8000")
    parser.add_argument("--start", action="store_true", help="Start scan")
    parser.add_argument("--stop", action="store_true", help="Stop scan")
    parser.add_argument("--band", default="20m")
    parser.add_argument("--start-hz", type=int, default=14000000)
    parser.add_argument("--end-hz", type=int, default=14350000)
    parser.add_argument("--step-hz", type=int, default=2000)
    parser.add_argument("--dwell-ms", type=int, default=250)
    parser.add_argument("--sample-rate", type=int, default=48000)
    parser.add_argument("--center-hz", type=int, default=14074000)
    parser.add_argument("--device-id", default=None)
    parser.add_argument("--scan-config-path", default=None, help="Path to scan YAML/JSON config")
    parser.add_argument("--region-profile-path", default=None, help="Path to region profile YAML/JSON")
    args = parser.parse_args()

    if args.start:
        if args.scan_config_path:
            payload = {
                "scan_config_path": args.scan_config_path
            }
        else:
            payload = {
                "scan": {
                    "band": args.band,
                    "start_hz": args.start_hz,
                    "end_hz": args.end_hz,
                    "step_hz": args.step_hz,
                    "dwell_ms": args.dwell_ms,
                    "mode": "auto",
                    "sample_rate": args.sample_rate,
                    "center_hz": args.center_hz,
                    "device_id": args.device_id
                }
            }

        if args.region_profile_path:
            payload["region_profile_path"] = args.region_profile_path

        print(_post_json(f"{args.host}/api/scan/start", payload))
        return

    if args.stop:
        print(_post_json(f"{args.host}/api/scan/stop", {}))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
