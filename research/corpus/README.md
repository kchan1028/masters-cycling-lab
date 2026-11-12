# Research corpus

20 open-access papers (CC BY) about masters cyclists, masters athletes and cycling training, used for search and
for the labelled evaluation. [`manifest.jsonl`](manifest.jsonl) is the source of truth: one line per paper with its
bibliographic data, where the PDF came from, its licence, the PDF's SHA-256, and a short description of the study
population.

The PDFs themselves are not in git (`pdfs/` is ignored). Fetch them with:

```bash
make corpus-download
```

```bash
make corpus-verify
```

```bash
make corpus-ingest
```

`corpus-download` fetches each PDF from its recorded URL and keeps it only if the SHA-256 matches the manifest.
`corpus-verify` checks every local file's size, SHA-256 and title, and reports how many are searchable.
`corpus-ingest` uploads them through the normal pipeline (duplicates are skipped) and sets their metadata from the
manifest, marked `manifest_verified`. Running it again resets these papers' metadata to the manifest, so make
corrections in `manifest.jsonl`, not through `PATCH /documents/{id}`.

## How the papers were chosen (2026-11-12)

1. **Search.** Europe PMC REST API, restricted to open-access articles with a PDF and a CC BY or CC0 licence,
   sorted by citation count. Six searches: masters/master/older/veteran cyclists; masters athletes and ageing;
   strength or resistance training in cyclists; training intensity distribution or polarized training in
   cycling; recovery in masters or older athletes; ageing and endurance performance or VO2max.
2. **Screening.** Titles and abstracts read for relevance to the project's topics (ageing, endurance performance,
   strength training, recovery, training intensity distribution, cycling physiology). Off-topic hits were dropped
   (bicycle safety, falls, battery chemistry, rodent studies, heart-failure patients).
3. **Balance.** The set deliberately mixes populations so the system can be tested on telling them apart:

   | `population_relevance` | Papers | Meaning |
   |---|---|---|
   | `masters_cyclists` | 5 | The study population is masters (or veteran) cyclists |
   | `age_comparison_cyclists` | 2 | Older and younger cyclists compared directly |
   | `masters_athletes_mixed_sports` | 5 | Masters athletes, cyclists among other sports or unspecified |
   | `masters_athletes_other_sport` | 2 | Masters runners only |
   | `adult_cyclists` | 5 | Cyclists not selected for age (recreational to professional) |
   | `endurance_athletes_mixed` | 1 | Young well-trained athletes from several endurance sports |

4. **Acquisition.** PDFs come from NCBI's PMC Open Access dataset on AWS Open Data
   (`pmc-oa-opendata.s3.amazonaws.com`), the channel NCBI provides for programmatic access. Each article's metadata
   file there supplies the licence code, a retraction flag and the PDF's MD5, which was checked on download. The
   Europe PMC "render PDF" links were tried first; they refuse automated requests (HTTP 403), so they were not used.
5. **Checks.** None of the 20 is marked retracted. Every PDF contains its recorded title on page 1 or 2. All are full
   text, none abstract-only.

Candidates considered but not included: junior vs senior cyclists' NIRS thresholds (PMC10892087, narrow
methodological topic), Berlin Marathon participation trends (PMC8273432, performance statistics only), a
polarized-training pilot in triathletes (PMC7689383) and polarized training in mountain bikers (PMC8296496), both
overlapping papers already included.

## What is and isn't verified

- **Verified against the source:** title (also checked against the PDF text), authors, year, DOI, PMCID, citation,
  licence, file hash. These come from PMC and Europe PMC metadata.
- **Provisional:** `population`, `age_range`, `sport`, `study_design` and `topics` were summarized from each
  abstract and methods section by Claude (an AI). Ages were read from the paper where the abstract didn't give them.
  Every entry has `description_review_status: provisional` until a person checks it against the paper.

## Licensing

All 20 are CC BY: they may be copied and redistributed with attribution. The PDFs are still kept out of the
repository to keep it small; the manifest records the attribution (authors, citation, DOI) and the source. The
software licences are covered in [docs/dependencies.md](../../docs/dependencies.md).

## Known limits of this corpus

- 20 papers is small. Evaluation results on it are indicative, not general.
- Open-access CC BY papers over-represent some journals (Frontiers, MDPI, BMC, Springer open access). Important
  closed-access studies on masters cyclists are missing.
- Only five papers study masters cyclists directly, and most samples are small (n = 10 to 125, plus one survey of
  555). Several "masters" findings come from runners or mixed sports and do not transfer to cyclists automatically.
- Selection favoured highly cited papers, which leans towards older publications for some topics.
