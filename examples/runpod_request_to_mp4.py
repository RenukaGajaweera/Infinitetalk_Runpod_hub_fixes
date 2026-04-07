#!/usr/bin/env python3
import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RUN_URL_DEFAULT = "https://api.runpod.ai/v2/kw7b83g3s25g0f/run"

DEFAULT_PAYLOAD = {
    "input": {
        "image_url": "https://storage.googleapis.com/viralnow-avatars-stg/ChatGPT%20Image%20Mar%2031%2C%202026%2C%2003_58_39%20PM.png",
        "wav_url": "https://storage.googleapis.com/viralnow-avatars-stg/ElevenLabs_v3_voice_script_segment_2.mp3",
        "prompt": "A single person speaking naturally, realistic lip sync, natural blinking, subtle head and upper-body motion, stable identity, talking avatar.",
        "width": 432,
        "height": 768,
        "fps": 25,
        "force_offload": True,
        "return_base64": False,
        "duration": 16
    }
}


def http_json(url: str, api_key: str, body: dict | None = None) -> dict:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(url=url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} for {url}: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Request failed for {url}: {e}") from e


def extract_video_base64(payload: dict) -> str | None:
    # Common RunPod response shapes:
    # 1) {"output": {"video": "..."}}
    # 2) {"video": "..."}
    # 3) status payloads with same nested shapes
    out = payload.get("output")
    if isinstance(out, dict):
        video = out.get("video")
        if isinstance(video, str) and video:
            return video

    video = payload.get("video")
    if isinstance(video, str) and video:
        return video

    return None


def decode_video_to_mp4(video_value: str, output_path: Path) -> None:
    # Handle both plain base64 and data URL forms.
    if video_value.startswith("data:") and "," in video_value:
        video_value = video_value.split(",", 1)[1]

    try:
        mp4_bytes = base64.b64decode(video_value)
    except Exception as e:
        raise RuntimeError(f"Failed to decode base64 video: {e}") from e

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(mp4_bytes)


def status_url_from_run_url(run_url: str, job_id: str) -> str:
    # Convert .../run to .../status/{id}
    if run_url.endswith("/run"):
        return run_url[:-4] + f"/status/{job_id}"
    return run_url.rstrip("/") + f"/status/{job_id}"


def poll_until_done(
    run_url: str,
    api_key: str,
    first_response: dict,
    poll_interval: float,
    timeout_seconds: float,
) -> dict:
    # If output already exists, no polling needed.
    if extract_video_base64(first_response):
        return first_response

    # Async path: expect id and status.
    job_id = first_response.get("id")
    status = str(first_response.get("status", "")).upper()

    if not job_id:
        # Not enough info to poll; return original for better error message later.
        return first_response

    status_endpoint = status_url_from_run_url(run_url, job_id)
    started = time.time()

    while True:
        if timeout_seconds > 0 and (time.time() - started) > timeout_seconds:
            raise TimeoutError(
                f"Timed out after {timeout_seconds:.0f}s while waiting for job {job_id}"
            )

        # RunPod status endpoint is also POST with auth.
        current = http_json(status_endpoint, api_key, body={})
        status = str(current.get("status", "")).upper()
        print(f"Status: {status}")

        if status in {"COMPLETED", "SUCCESS"}:
            return current
        if status in {"FAILED", "CANCELLED", "TIMED_OUT"}:
            raise RuntimeError(f"RunPod job failed: {json.dumps(current, ensure_ascii=False)}")

        time.sleep(poll_interval)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Send a RunPod request and write returned base64 video as a single MP4 file."
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("RUNPOD_API_KEY", ""),
        help="RunPod API key. Defaults to RUNPOD_API_KEY environment variable.",
    )
    parser.add_argument(
        "--run-url",
        default=RUN_URL_DEFAULT,
        help="RunPod run endpoint URL.",
    )
    parser.add_argument(
        "--output",
        default="output/runpod_result.mp4",
        help="Output MP4 path.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=3.0,
        help="Polling interval in seconds for async responses.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=1800.0,
        help="Timeout in seconds for completion. Set 0 to disable timeout.",
    )
    args = parser.parse_args()

    if not args.api_key:
        print("Missing API key. Set RUNPOD_API_KEY or pass --api-key.", file=sys.stderr)
        return 2

    output_path = Path(args.output)

    print("Sending request to RunPod endpoint...")
    first = http_json(args.run_url, args.api_key, body=DEFAULT_PAYLOAD)
    print("Initial response:")
    print(json.dumps(first, indent=2, ensure_ascii=False))

    final_payload = poll_until_done(
        run_url=args.run_url,
        api_key=args.api_key,
        first_response=first,
        poll_interval=args.poll_interval,
        timeout_seconds=args.timeout,
    )

    print("Final response:")
    print(json.dumps(final_payload, indent=2, ensure_ascii=False))

    video_b64 = extract_video_base64(final_payload)
    if not video_b64:
        # If network volume mode is used, caller will get video_path instead of base64.
        if isinstance(final_payload.get("output"), dict) and final_payload["output"].get("video_path"):
            print(
                "Response returned output.video_path (network volume mode) instead of base64 video. "
                "No MP4 was written by this script.",
                file=sys.stderr,
            )
            return 3
        if final_payload.get("video_path"):
            print(
                "Response returned video_path instead of base64 video. No MP4 was written by this script.",
                file=sys.stderr,
            )
            return 3

        print("No video field found in response.", file=sys.stderr)
        return 4

    decode_video_to_mp4(video_b64, output_path)
    print(f"Wrote MP4: {output_path} ({output_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
