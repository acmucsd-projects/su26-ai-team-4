# Post-Disaster Building Damage Triage Assistant

## Setup
1. Clone this repo
2. Create the environment: `conda env create -f environment.yml`
3. Activate it: `conda activate disaster-triage`
4. Follow `data/README.md` to get the dataset
5. See `docs/` for scope decisions and research notes

## Running training
`python src/training/train.py --config configs/baseline.yaml`

## Running the app
`python app/app.py`

## Team
[names/roles]