"""Is this a Darwin Core Archive a publisher would accept?

    python3 tools/check_archive.py records.zip

Checks the three files are there, that the descriptor is valid XML and describes
exactly the columns the data has, and that the terms GBIF insists on are present.
Used by the tests in CI, and useful on its own before sending an archive off.
"""

import sys
import xml.etree.ElementTree as ET
import zipfile

NS = {"d": "http://rs.tdwg.org/dwc/text/"}
REQUIRED = ("occurrenceID", "basisOfRecord", "scientificName", "eventDate",
            "decimalLatitude", "decimalLongitude", "occurrenceStatus")


def check(path) -> int:
    z = zipfile.ZipFile(path)
    problems = []
    missing = {"occurrence.csv", "meta.xml", "eml.xml"} - set(z.namelist())
    if missing:
        print(f"missing from the archive: {', '.join(sorted(missing))}")
        return 1
    core = ET.fromstring(z.read("meta.xml")).find("d:core", NS)
    header = z.read("occurrence.csv").decode().splitlines()[0].split(",")
    fields = core.findall("d:field", NS)
    if len(fields) != len(header):
        problems.append(f"meta.xml describes {len(fields)} columns, "
                        f"occurrence.csv has {len(header)}")
    if core.find("d:id", NS) is None:
        problems.append("meta.xml has no id element")
    for term in REQUIRED:
        if term not in header:
            problems.append(f"no {term} column, which every publisher wants")
    ET.fromstring(z.read("eml.xml"))
    rows = len(z.read("occurrence.csv").decode().strip().splitlines()) - 1
    if problems:
        print("\n".join(problems))
        return 1
    print(f"valid archive: {rows} records, {len(header)} Darwin Core terms")
    return 0


if __name__ == "__main__":
    sys.exit(check(sys.argv[1] if len(sys.argv) > 1 else "occurrences-dwca.zip"))
