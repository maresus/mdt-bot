from __future__ import annotations

# Shared symptom/service hints used by both confidence routing and triage fallback.
# Keep this file focused on high-signal tokens to reduce drift between modules.

DERMATOLOGY_HINTS = {
    "koža",
    "koza",
    "izpuščaj",
    "izpuscaj",
    "madež",
    "madez",
    "znamenje",
    "bradavica",
    "bradavice",
    "srbi",
    "srbe",
    "akne",
}

ORTHOPEDICS_HINTS = {
    "koleno",
    "kolen",
    "hrbet",
    "hrbten",
    "rama",
    "ramo",
    "sklep",
    "zapestje",
    "zapestja",
    "zapestju",
    "gleženj",
    "glezenj",
    "poškodba",
    "poskodba",
    "zvin",
    "zlom",
}

OPHTHALMOLOGY_HINTS = {
    "oko",
    "očala",
    "ocala",
    "okulist",
    "oftalmolog",
}

URGENT_MEDICAL_HINTS = {
    "krv",
    "krvav",
    "krvavim",
    "dihanje",
    "diham",
    "prsih",
    "nezavest",
    "omedlev",
}
