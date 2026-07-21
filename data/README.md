# Data

Raw xBD data is NOT stored in this repo (too large for git).

## To get the data:
1. Register at https://xview2.org/dataset
2. Download the [disaster subsets we're using — fill in once Person 1 confirms]
3. Extract into this `data/` folder so it matches this structure:

data/
├── tier1/
│   ├── images/
│   └── labels/
├── tier3/
│   ├── images/
│   └── labels/

## Processed data
After running the preprocessing pipeline (`src/data/preprocess.py`), a manifest file will be generated at `data/manifest.csv` — this file IS tracked in git.