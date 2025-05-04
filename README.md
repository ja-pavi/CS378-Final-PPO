# Safe Autonomous Driving in HighwayEnv with PPO

**Authors:** Jacob Villanueva & Arnav Bagad  
**Course:** CS378/CSE392 – Geometric Foundations of Data Science, Spring 2025

This repository contains the source code and training pipeline for robust autonomous driving agents trained using Proximal Policy Optimization (PPO) in the [HighwayEnv](https://github.com/eleurent/highway-env) simulation suite. Our agents operate in both highway and roundabout environments under noisy and uncertain conditions, leveraging skill abstraction, confidence estimation, and rule-based safety overrides.

---

## Installation (Though Colab link is recommended to run)

To run the code, install the following dependencies:

```bash
!pip install highway-env
!pip install git+https://github.com/DLR-RM/stable-baselines3
!pip install tensorboardx pyvirtualdisplay
!apt-get install -y xvfb ffmpeg
```

---

## Running the Demo

The uploaded version on the repo is a .py file as the .ipynb was too large.

A Jupyter notebook / Google Colab version of this code is available for interactive testing and video playback in **Google Colab**. It includes:

- Environment setup
- Custom wrappers for safety, confidence, and skill abstraction
- `train_and_evaluate()` pipeline
- TensorBoard logging
- Video rendering of evaluation episodes

> **To run the notebook in Colab**:  
> - Click [here](https://colab.research.google.com/drive/1fY-S9kfjXP3lDBQm3ibs5kNwXyZV5a9i?usp=sharing) to open the notebook  
> - Execute all cells  
> - Use `%tensorboard --logdir <path>` to visualize training progress

---

## Project Structure

```
.
├── train_and_evaluate.py       # Main training + evaluation loop
├── wrappers.py                 # Custom Gym wrappers (noise, confidence, skills)
├── safety_wrappers.py          # SafePolicy and SafeSkillPolicy logic
├── configs.py                  # Environment configurations (highway & roundabout)
├── utils.py                    # Utility functions for metrics, logs
├── ppo_logs/                   # TensorBoard logs per experiment
├── ppo_videos/                 # Rendered evaluation videos
└── README.md                   # This file
```

---

## Features

- **Environments**: `highway-fast-v0`, `roundabout-v0` with aggressive vehicles  
- **Skill Abstraction**: Learn macro-actions like `FOLLOW`, `OVERTAKE`, and `KEEP_RIGHT`  
- **SafePolicy Wrappers**: Confidence-aware rule-based overrides to prevent risky behavior  
- **Noisy Observations**: Simulate real-world sensor noise and partial observability  
- **Intention Modeling**: Augment state space with inferred or synthetic vehicle intentions  
- **Evaluation Tools**: Logs lane changes, crashes, reward, and average confidence per episode  
- **Video Logging**: Save evaluation rollouts using `RecordVideo`  
- **TensorBoard**: View real-time training metrics using `%tensorboard`

---

## How It Works

Each experiment is launched using the `train_and_evaluate()` function, which takes the environment ID and toggles for noise, safety wrappers, and skill abstraction. The pipeline:

1. **Creates a Gym environment** using `make_custom_env()` with optional noise, confidence, intention augmentation, and safety overrides.
2. **Trains a PPO agent** using Stable-Baselines3 with a multi-layer perceptron policy and logs to TensorBoard.
3. **Evaluates the trained policy** using a video recorder and statistics wrapper, including optional safety override wrappers during evaluation.
4. **Logs episode metrics** like reward, lane changes, crash rate, and average confidence.

---

## Summary of Key Modules

| Code Block / Class              | Description                                                                 |
|--------------------------------|-----------------------------------------------------------------------------|
| `SafePolicyWrapper`            | Overrides PPO actions if confidence is low; avoids risky behavior.         |
| `SafeSkillPolicyWrapper`       | Does the same for skill-based policies, forcing conservative behavior.      |
| `SkillEnv`                     | Converts high-level skill actions (like OVERTAKE) into low-level primitives.|
| `NoisyObservationWrapper`      | Injects Gaussian noise into key vehicle features.                          |
| `ConfidenceWrapper`            | Adds a confidence channel using feature variance.                          |
| `IntentionWrapper`             | Appends a synthetic intention label based on lateral velocity.             |
| `train_and_evaluate()`         | Trains and evaluates PPO models with logging and video rendering.          |

---

## Running a Configuration

To run a specific variant (e.g., with noise + safety), call:

```python
train_and_evaluate(
    env_id="highway-fast-v0",
    model_name="ppo_noise_safe",
    log_subdir="./ppo_logs/ppo_noise_safe/",
    video_subdir="./ppo_videos/ppo_noise_safe/",
    noise=True,
    noise_level=0.5,
    intention=False,
    safe_policy=True,
    skill_abstraction=False
)

