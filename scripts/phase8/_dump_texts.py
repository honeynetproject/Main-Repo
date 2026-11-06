"""Write n random TEST-split training texts to a JSON file: _dump_texts.py N SEED OUT."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _testdata import sample_test_sessions  # noqa: E402

n, seed, out = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
_, _, texts = sample_test_sessions(n, seed)
Path(out).write_text(json.dumps(texts))
