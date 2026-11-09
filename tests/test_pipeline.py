"""Offline tests on synthetic pages (run: python -m pytest -q  or  python tests/test_pipeline.py)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from leadpipe import load_config
from leadpipe.discover import _parse_directory_page
from leadpipe.extract_llm import quote_is_grounded
from leadpipe.extract_rules import extract
from leadpipe.profiles import parse_profile
from leadpipe import score as sc

DIR_HTML = """<ul>
<li><a href="/hausverwaltung/biddex-hausverwaltungen-berlin">BIDDEX Hausverwaltungen ></a><p>Marburger Str. 17, 10789 Berlin</p></li>
<li><a href="/hausverwaltung/bhs-hausverwaltung-braunschweig">BHS Hausverwaltung ></a><p>Berliner Heerstr. 57, 38104 Braunschweig</p></li>
</ul>"""

PROFILE_HTML = """<h1>Pöppel Immobilien</h1><p>4,9 65 Bewertungen auf 1 Portal</p>
<p>62+ Mitarbeiter</p><p>seit 1991 in Berlin tätig</p><a href="https://www.poeppel-immobilien.de">zur Webseite</a>
<a href="https://www.google.com/maps">Google</a>"""

PAGES = [
    {"role": "home", "url": "https://x.de", "text": "Ihre Hausverwaltung in Berlin. Wir verwalten über 2.500 Wohneinheiten in Berlin, "
                                                     "vor allem Altbau aus der Gründerzeit. Mietverwaltung und WEG-Verwaltung aus einer Hand. "
                                                     "Unser Mieterportal ist rund um die Uhr erreichbar."},
    {"role": "services", "url": "https://x.de/leistungen", "text": "Wir erstellen die Betriebskostenabrechnung. "
                                                                    "Die Heizkostenabrechnung erfolgt in Zusammenarbeit mit Techem. Wir arbeiten mit DOMUS."},
    {"role": "impressum", "url": "https://x.de/impressum", "text": "Impressum\nMuster Hausverwaltung GmbH\nGeschäftsführer: Dr. Anna Schmidt, Peter Müller\n"
                                                                    "Amtsgericht Charlottenburg HRB 123456 B\nTel.: 030 1234567\nE-Mail: info@x.de\n"
                                                                    "a.schmidt@x.de\nMitglied im VDIV Berlin-Brandenburg"},
]


def test_directory_parser():
    rows = _parse_directory_page(DIR_HTML, "https://www.jacasa.de/hausverwaltung-verzeichnis/b?page=1")
    assert len(rows) == 2 and rows[0]["postcode"] == "10789" and rows[0]["name"] == "BIDDEX Hausverwaltungen"
    assert rows[0]["street"].startswith("Marburger")


def test_profile_parser():
    p = parse_profile(PROFILE_HTML)
    assert p["website"] == "https://www.poeppel-immobilien.de" and p["employees"] == 62
    assert p["founded"] == 1991 and p["review_count"] == 65 and p["rating"] == 4.9


def test_rules_and_score():
    r = extract(PAGES)
    assert r["units"]["value"] == 2500 and r["weg"]["value"] and r["miet"]["value"]
    assert r["metering_provider"]["value"] == "Techem"
    assert "Anna Schmidt" in r["decision_makers"]["value"] and "Peter Müller" in r["decision_makers"]["value"]
    assert r["email_personal"]["value"] == "a.schmidt@x.de" and r["email_generic"]["value"] == "info@x.de"
    assert r["register_number"]["value"].startswith("HRB 123456")
    assert "VDIV" in r["memberships"]["value"] and r["software"]["value"] == "DOMUS"
    f = sc.merge(r, None, {"employees": 20})
    s = sc.score(f, load_config()["weights"])
    assert s["total"] >= 80, s
    assert "Techem" in sc.sales_angle(f, s)


def test_hallucination_guard():
    src = "Wir verwalten über 2.500 Wohneinheiten in Berlin."
    assert quote_is_grounded("verwalten über 2.500 Wohneinheiten", src)
    assert not quote_is_grounded("verwalten über 5.000 Wohneinheiten", src)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("passed", name)
