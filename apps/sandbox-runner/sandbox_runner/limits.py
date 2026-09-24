"""Per-execution container limits (docs/24 §4)."""

MEMORY_BYTES = 256 * 1024 * 1024
NANO_CPUS = 500_000_000
PIDS_LIMIT = 64
OUTPUT_CAP = 64 * 1024
MAX_IMAGES = 3
MAX_IMAGE_BYTES = 1024 * 1024
MAX_CODE_CHARS = 20_000
MAX_INPUT_FILES = 5
MAX_INPUT_BYTES = 10 * 1024 * 1024
MAX_TIMEOUT_SECONDS = 30
CONTAINER_TTL_SECONDS = 60
SLOT_WAIT_SECONDS = 2.0

TMPFS = {
    "/work": "rw,size=64m,uid=65534,gid=65534,mode=0700,noexec",
    "/tmp": "rw,size=16m,noexec",  # noqa: S108 - tmpfs inside the sandbox container
}
ENV = {"PYTHONUNBUFFERED": "1", "MPLBACKEND": "Agg", "HOME": "/work"}
ULIMITS = [
    {"Name": "nofile", "Soft": 256, "Hard": 256},
    {"Name": "fsize", "Soft": 16 * 1024 * 1024, "Hard": 16 * 1024 * 1024},
    {"Name": "nproc", "Soft": 64, "Hard": 64},
]
