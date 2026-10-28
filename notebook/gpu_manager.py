"""Hardware discovery is separate from validating CUDA inference."""
import subprocess


def detect_gpu():
    try:
        completed = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=False)
        if completed.returncode == 0 and completed.stdout.strip():
            parts = completed.stdout.strip().splitlines()[0].split(",", 1)
            name = parts[0].strip()
            vram = float(parts[1]) / 1024 if len(parts) > 1 else 0.0
            return {"detected": True, "name": name, "vram": f"{vram:.1f} GB"}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return {"detected": False, "name": "CPU", "vram": "0 GB"}
