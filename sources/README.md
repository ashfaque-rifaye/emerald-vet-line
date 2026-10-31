# Source documents

Emerald only states what these documents say. `passages.jsonl` holds excerpts from them, each with its source, PDF page and hash.
The PDFs themselves are not in this repo. To rebuild the excerpts, download them into `sources/raw/` and run `python scripts/ingest_sources.py`.

| File | Document | Publisher | Where to get it |
|---|---|---|---|
| `raw/svtg/svtg-2024.pdf` | Standard Veterinary Treatment Guidelines for Livestock and Poultry (2024) | Department of Animal Husbandry and Dairying, Government of India, with FAO and USAID support | The department's link is currently dead; [archived copy](https://web.archive.org/web/2025/https://dahd.gov.in/sites/default/files/2024-10/StandardVeterinaryTreatment.pdf) |
| `raw/fao-lsd/fao-lsd-manual.pdf` | Lumpy skin disease: A field manual for veterinarians (2017) | Food and Agriculture Organization of the United Nations | [FAO repository](https://openknowledge.fao.org/server/api/core/bitstreams/1c277d5a-b2eb-42f3-a32a-9c71fde089f0/content) |
| `raw/act2009/act-2009.pdf` | Prevention and Control of Infectious and Contagious Diseases in Animals Act, 2009 | Parliament of India | [PRS India](https://prsindia.org/files/bills_acts/acts_parliament/2009/the-prevention-and-control-of-infectious-and-contagious-diseases-in-animals-act,-2009.pdf) |

## What was left out on purpose

Laboratory methods, sample collection and pathogen handling are filtered out during ingestion. Emerald's job ends at "call the vet", so it has no use for them. A test keeps it that way.

## Limits of these sources

- The treatment guidelines describe themselves as advisory, for veterinary professionals, and not as binding regulation.
- The Act's text says it does not apply in Uttar Pradesh, and a draft amendment was published in December 2025. Check the current version before relying on it.
- The guideline entries used here give no milk withdrawal periods, so Emerald leaves that for the vet rather than guessing.
