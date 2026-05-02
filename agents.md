- Directory Structure: When creating or writing experimental scripts, always explicitly use the following directory structure inside the corresponding experiment folder (`<exp_name>`):
  - `<exp_name>/checkpoint`: Used to saving model weights, state dicts, and checkpoints.
  - `<exp_name>/results`: Used to save evaluation results, output logs, CSV files, and plotted figures.

- Training Scripts: Hyper Parameters such as `DATASET_NAME`, `TRAIN_RATIO`, `VAL_RATIO`, `BATCH_SIZE`, `EPOCHS`, and `LR` should be extracted to the head of the experiment file (e.g. `train.py`) to easily control the standard dataset split and iteration configuration.
