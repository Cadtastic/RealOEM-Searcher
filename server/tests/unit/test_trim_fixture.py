from pathlib import Path

from scripts.trim_fixture import main, mask_vins, trim

RAW = """<!DOCTYPE html>
<html><head>
<!-- tracking tag -->
<script>window.ads = 1;</script>
<script src="/cdn-cgi/challenge-platform/main.js"></script>
<script type="application/ld+json">{"@type":"BreadcrumbList"}</script>
<link rel="stylesheet" href="/bmw/css/common.css">
<link rel="alternate" hreflang="de" href="https://www.realoem.com/bmw/de/partgrp">
<link rel="canonical" href="https://www.realoem.com/bmw/enUS/partgrp?id=VB13">
<style>body { color: red }</style>
<title>Parts</title>
</head><body>
<div id="realoem-com_leaderboard_atf"><div>ad</div></div>
<iframe src="https://ads.example/"></iframe>
<ins class="adsbygoogle"></ins>
<div class="content"><h1>11427953129</h1>
<a class="ecs-tuning-button" data-ecs-part-number="11427953129"
   data-ecs-part-name="Set oil-filter element" href="https://click.example/">
   Shop this part <span>at ECS</span></a>
<p>VIN WBATEST0000000001 and serial 0000001</p>
<a href="/login?next=%2fselect%3fvin%3dWBATEST0000000001">Sign In</a>
<a href="/share?u=%2fvin%2FWBATEST0000000001">Share</a>
</div>
<table id="partsList"><tr class="pos01"><td>01</td>
<td class="ecs-tuning-cell"> <a class="ecs-tuning-link" data-ecs-part-name="Oil Pan"
   href="https://click.example/pan">Shop</a> </td></tr></table>
<p><a class="ecs-tuning-link" href="https://click.example/loose">ECS</a></p>
<div id="partsimg"><script>var partsimgmap=[["01",78,255,87,271]];</script></div>
</body></html>
"""


def test_removes_scripts_except_json_ld_and_partsimgmap() -> None:
    out = trim(RAW)
    assert "window.ads" not in out
    assert "challenge-platform" not in out
    assert '<script type="application/ld+json">{"@type":"BreadcrumbList"}</script>' in out
    assert 'var partsimgmap=[["01",78,255,87,271]];' in out


def test_removes_chrome_but_keeps_canonical_link() -> None:
    out = trim(RAW)
    for gone in ("<style", "<iframe", "<ins", "tracking tag", "realoem-com_", "stylesheet"):
        assert gone not in out
    assert 'hreflang="de"' not in out
    assert '<link rel="canonical" href="https://www.realoem.com/bmw/enUS/partgrp?id=VB13">' in out
    assert "<h1>11427953129</h1>" in out


def test_keeps_only_ecs_class_and_part_name_and_empties_the_button() -> None:
    out = trim(RAW)
    assert '<a class="ecs-tuning-button" data-ecs-part-name="Set oil-filter element"></a>' in out
    assert "click.example" not in out
    assert "data-ecs-part-number" not in out
    assert "Shop this part" not in out
    assert "at ECS" not in out


def test_removes_ecs_links_and_empties_their_cells() -> None:
    out = trim(RAW)
    assert "ecs-tuning-link" not in out
    assert "click.example/pan" not in out
    assert "click.example/loose" not in out
    assert '<td class="ecs-tuning-cell"></td>' in out
    assert "<td>01</td>" in out


def test_masks_full_vins_everywhere() -> None:
    out = trim(RAW)
    assert "WBATEST0000000001" not in out
    assert "VIN XXXXXXXXXX0000001 and serial 0000001" in out
    assert "vin%3dXXXXXXXXXX0000001" in out
    assert "vin%2FXXXXXXXXXX0000001" in out


def test_mask_vins_leaves_part_numbers_and_words_alone() -> None:
    text = "11427953129 ABCDEFGHJKLMNPRST 12345678901234567 WBATEST0000000001X"
    assert mask_vins(text) == text


def test_trim_is_idempotent() -> None:
    once = trim(RAW)
    assert trim(once) == once
    assert once.endswith("</html>\n")


def test_cli_writes_trimmed_file(tmp_path: Path) -> None:
    raw = tmp_path / "raw.html"
    raw.write_text(RAW, encoding="utf-8")
    out = tmp_path / "fixtures" / "partgrp" / "sample.html"
    assert main([str(raw), str(out)]) == 0
    assert out.read_text(encoding="utf-8") == trim(RAW)
