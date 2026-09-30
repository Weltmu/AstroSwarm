import sys
import time

import pytest

from astroswarm_linux import proc

posix = sys.platform != "win32"


@pytest.mark.skipif(not posix, reason="posix only")
def test_spawn_and_kill_tree(tmp_path):
    log = tmp_path / "out.log"
    p = proc.spawn(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        cwd=tmp_path,
        env={},
        log_path=log,
    )
    assert proc.is_alive(p)
    proc.kill_tree(p)
    for _ in range(100):
        if not proc.is_alive(p):
            break
        time.sleep(0.05)
    assert not proc.is_alive(p)
