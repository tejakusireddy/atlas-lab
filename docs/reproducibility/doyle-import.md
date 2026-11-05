# Doyle reaction-table import

Run `uv run --locked atlas-import --download` to fetch the pinned public table and its license, verify both SHA-256 digests, and normalize a new local snapshot. Without `--download`, the command requires already verified local files. Existing snapshots are never overwritten; choose a new `--output` path for a fresh run.

The source is [doylelab/rxnpredict](https://github.com/doylelab/rxnpredict/tree/57e15fdb7f7483c6bf3a601df69f6ac9e5af6965), accompanying Ahneman et al., [Science (2018)](https://doi.org/10.1126/science.aar5169). The repository includes an MIT license. Raw files, the license copy, normalized data, and rejected rows remain in ignored local `data/` directories.

The table omits a separate amine column. Its fixed amine, `Cc1ccc(N)cc1`, was verified against all 4,312 `Dreher Doyle 2018` rows in the [curated dataset at revision 3a44e39](https://github.com/schwallergroup/bh-hte-ood/tree/3a44e398d9fed3f08cf396f1153be2960193f581). The importer records that file's checksum and evidence column. Curated rows are not added as independent training observations.

## Output and integrity

- `candidates.jsonl` contains typed, outcome-free identities and role-tagged original/canonical SMILES.
- `oracle/observations.jsonl` preserves source yields, row references, units through the schema, and QC outcomes.
- `oracle/rejected.json` preserves rejected source rows and reasons. It contains labels and must stay within the oracle boundary.
- `quality_report.json` records input, rejection, QC, and eligible-group counts.
- `source_manifest.json` records source revision, file/license checksums, normalization and RDKit versions, DOI, identity evidence, limitations, and output checksums.

Rows without required molecules are rejected. Empty additive fields explicitly mean no additive. Reaction identities include canonical aryl, amine, base, ligand, and additive roles; duplicate identities are rejected rather than counted as new experiments. Yields are interpreted as percentages, without clipping or imputation. Invalid values are quarantined, missing values are unobserved, and zero remains a valid measured outcome.

The first verified import produced 4,312 unique eligible candidates from 4,599 source rows. It excluded 287 blank-substrate controls. All retained outcomes passed range checks; 15 substrate groups contain 286–288 candidates each. These are ingestion counts, not predictive model results.

## Limits

The fixed amine is shared across groups. A held-out aryl/amine pair in this dataset does not establish generalization to two unseen substrates. Strict exclusion of both substrate identities leaves no external training data. Cross-source near-duplicate normalization remains future work.

Separate files and restrictive local permissions prevent accidental label mixing, but are not an execution security boundary. The application must enforce oracle access through a separate service and approved simulation lifecycle before offering campaign execution. The importer alone does not provide that boundary.
