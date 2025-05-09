# -*- coding: utf-8 -*-
"""PPO Clean

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1fY-S9kfjXP3lDBQm3ibs5kNwXyZV5a9i
"""

!pip install highway-env
!pip install git+https://github.com/DLR-RM/stable-baselines3
!pip install tensorboardx pyvirtualdisplay
!apt-get install -y xvfb ffmpeg

import os
import numpy as np
import gymnasium as gym
import highway_env
from tqdm.auto import trange
from stable_baselines3 import PPO
from gymnasium.wrappers import RecordVideo, RecordEpisodeStatistics
from stable_baselines3.common.vec_env import SubprocVecEnv, DummyVecEnv, VecMonitor

# Commented out IPython magic to ensure Python compatibility.
# %load_ext tensorboard

import numpy as np

class SafePolicyWrapper:
    def __init__(self, base_policy, threshold=1.0):
        self.base_policy    = base_policy
        self.threshold      = threshold
        self.observation_space = base_policy.observation_space
        self.action_space      = base_policy.action_space
        self.override_log      = []

    def compute_risk_confidence(self, obs_mat):
      ego_x = obs_mat[0][0]
      ego_lane = int(obs_mat[0][1])
      distances = []
      for v in obs_mat[1:]:
          other_x, other_lane = v[0], int(v[1])
          if other_lane == ego_lane:
              dist = other_x - ego_x
              if 0 <= dist < 3.0:
                  distances.append(dist)

      if len(distances) == 0:
          return 1.0
      else:
          min_dist = min(distances)
          return np.clip(min_dist / 3.0, 0.0, 1.0)


    def predict(self, observation, deterministic=True):
        obs_mat = observation if isinstance(observation, np.ndarray) else observation["observation"]
        ego      = obs_mat[0]
        conf = self.compute_risk_confidence(obs_mat)
        conf = 0.5 * float(ego[-1]) + (0.5) * conf
        vx       = float(ego[2])
        if conf <= self.threshold:
            if vx < 0.5:
                act, label = 3, "ACCELERATE"
            elif vx > 1:
                act, label = 4, "DECELERATE"
            else:
                act, label = 1, "KEEP_LANE"
            self.override_log.append((conf, label))
            return np.array([act]), None

        # Defer to the learned policy
        return self.base_policy.predict(observation, deterministic=deterministic)

import numpy as np

SKILLS = {
    0: "FOLLOW",
    1: "OVERTAKE_LEFT",
    2: "OVERTAKE_RIGHT",
    3: "SLOW_DOWN",
    4: "KEEP_RIGHT"
}
SKILL2ACTION = {
    0: [1, 1, 1, 1],
    1: [2, 3, 3, 0],
    2: [0, 3, 3, 2],
    3: [4, 4, 4, 4],
    4: [0, 0, 1, 1],
}

class SafeSkillPolicyWrapper:
    def __init__(self, base_model, threshold=0.7):
        self.base_model    = base_model
        self.threshold     = threshold
        self.override_log  = []
        self.observation_space = base_model.observation_space
        self.action_space      = base_model.action_space

    def predict(self, obs, deterministic=True):
        skill_idx, state = self.base_model.predict(obs, deterministic=deterministic)
        skill_idx = int(skill_idx)

        mat = obs if isinstance(obs, np.ndarray) else obs["observation"]
        ego = mat[0]
        conf = float(ego[-1])

        if conf < self.threshold:
            self.override_log.append((conf, SKILLS[skill_idx], "SLOW_DOWN"))
            return np.array([3]), state

        return np.array([skill_idx]), state

class SkillEnv(gym.Wrapper):
    def __init__(self, env, skill2action):
        super().__init__(env)
        self.skill2action = skill2action
        self.action_space = gym.spaces.Discrete(len(skill2action))

    def step(self, skill):
        if isinstance(skill, np.ndarray):
            skill = int(skill.squeeze())
        else:
            skill = int(skill)

        total_reward = 0
        done = False
        last_terminated = False
        last_truncated = False
        info = {}

        for a in self.skill2action[skill]:
            obs, reward, terminated, truncated, info = self.env.step(a)
            total_reward += reward
            last_terminated = terminated
            last_truncated  = truncated
            if terminated or truncated:
                done = True
                break

        return obs, total_reward, last_terminated, last_truncated, info

import gymnasium as gym
import numpy as np

class NoisyObservationWrapper(gym.ObservationWrapper):
    def __init__(self, env, noise_std=0.5):
        super().__init__(env)
        self.noise_std = noise_std

    def observation(self, obs):
        obs = obs.copy()
        if isinstance(obs, dict):
            obs_matrix = obs["observation"]
        else:
            obs_matrix = obs

        noise = np.random.normal(0, self.noise_std, size=obs_matrix[:, 1:5].shape)
        obs_matrix[:, 1:5] += noise

        return obs

import numpy as np
from gymnasium import ObservationWrapper, spaces

class ConfidenceWrapper(ObservationWrapper):
    def __init__(self, env):
        super().__init__(env)
        original_shape = self.observation_space.shape  # e.g., (5, 5)
        V, F = original_shape
        new_shape = (V, F + 1)
        self.observation_space = spaces.Box(
            low=-np.inf,
            high=np.inf,
            shape=new_shape,
            dtype=np.float32
        )

    def observation(self, obs):
        obs = obs.copy()
        obs_matrix = obs["observation"] if isinstance(obs, dict) else obs
        confidence = np.exp(-np.var(obs_matrix[:, 1:5], axis=1, keepdims=True))
        obs_augmented = np.concatenate([obs_matrix, confidence], axis=1)
        return obs_augmented

class IntentionWrapper(gym.ObservationWrapper):
    def __init__(self, env):
        super().__init__(env)
        V, F = self.observation_space.shape
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf,
            shape=(V, F + 1),
            dtype=np.float32
        )

    def observation(self, obs):
        def infer_intention(vy):
            if vy > 0.3:
                return 1
            elif vy < -0.3:
                return -1
            else:
                return 0
        obs_matrix = obs["observation"] if isinstance(obs, dict) else obs
        intentions = np.array([[infer_intention(vy)] for vy in obs_matrix[:, 4]])
        obs_augmented = np.concatenate([obs_matrix, intentions], axis=1)
        return obs_augmented

def make_custom_env(
    env_id,
    noise=False,
    noise_level=0.5,
    intention=False,
    synthetic_intent=False,
    env_config=None,
    skill_abstraction=False,
    safe_policy=False,
):
    def _init():
        env = (
            gym.make(env_id, render_mode="rgb_array", config=env_config)
            if env_config
            else gym.make(env_id, render_mode="rgb_array")
        )

        if noise:
            env = NoisyObservationWrapper(env, noise_std=noise_level)
            env = ConfidenceWrapper(env)

        if intention:
            env = IntentionWrapper(env)

        if skill_abstraction:
            env = SkillEnv(env, SKILL2ACTION)

        if safe_policy:
            env = SafePolicyWrapper(env, threshold=1.0)

        return env

    return _init

# Commented out IPython magic to ensure Python compatibility.
def train_and_evaluate(
    env_id,
    model_name,
    log_subdir,
    video_subdir,
    noise=False,
    noise_level=0.5,
    intention=False,
    synthetic_intent=False,
    env_config=None,
    num_eval_episodes=10,
    total_timesteps=10000,
    vectorized=False,
    n_envs=4,
    safe_policy=False,
    skill_abstraction=False
):
    os.makedirs(log_subdir, exist_ok=True)
    os.makedirs(video_subdir, exist_ok=True)

    if vectorized:
        env_fns = [
            make_custom_env(env_id, noise, noise_level, intention, synthetic_intent, env_config, skill_abstraction)
            for _ in range(n_envs)
        ]
        train_env = SubprocVecEnv(env_fns)
        train_env = VecMonitor(train_env)
    else:
        train_env = make_custom_env(
            env_id, noise, noise_level, intention, synthetic_intent, env_config, skill_abstraction
        )()

    # Train
    model = PPO(
        "MlpPolicy",
        train_env,
        policy_kwargs=dict(net_arch=[dict(pi=[256, 256], vf=[256, 256])]),
        n_steps=1024,
        batch_size=64,
        n_epochs=10,
        learning_rate=5e-4,
        gamma=0.8,
        verbose=1,
        tensorboard_log=log_subdir
    )
    model.learn(total_timesteps=total_timesteps)
    model.save(model_name)
    train_env.close()

    # TensorBoard
    print(f"Finished training {model_name}")
    print(f" Launching TensorBoard for {model_name}")
#     %tensorboard --logdir $log_subdir

    # Evaluation env
    eval_env = make_custom_env(
        env_id, noise, noise_level, intention, synthetic_intent, env_config, skill_abstraction
    )()
    eval_env = RecordVideo(
        eval_env,
        video_folder=video_subdir,
        name_prefix=f"{model_name}_eval",
        episode_trigger=lambda x: True
    )
    eval_env = RecordEpisodeStatistics(eval_env, buffer_length=num_eval_episodes)
    model = PPO.load(model_name)

    # Check safety or skill
    if safe_policy and skill_abstraction:
        policy = SafeSkillPolicyWrapper(model, threshold=0.65)
    elif safe_policy:
        policy = SafePolicyWrapper(model.policy, threshold=0.7)
    else:
        policy = model

    # Eval
    rewards, lengths, crashes = [], [], []
    lane_changes, high_speed_steps, idle_steps = [], [], []
    all_avg_confs = []

    for ep in trange(num_eval_episodes, desc="Evaluating", leave=False):
        obs, _ = eval_env.reset()
        done = False
        crashed = False
        total_reward = 0
        ep_lane_changes = ep_high_speed = ep_idle = 0
        confidences = []

        while not done:
            action, _ = policy.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, info = eval_env.step(action)
            done = terminated or truncated

            total_reward += reward
            ego_obs = obs[0] if isinstance(obs, np.ndarray) else obs["observation"][0]
            conf, vx, vy = ego_obs[-1], ego_obs[2], ego_obs[3]
            confidences.append(conf)

            if abs(vy) > 0.2: ep_lane_changes += 1
            if vx > 1:     ep_high_speed += 1
            if vx <= 1:    ep_idle += 1
            if info.get("crashed", False): crashed = True

        rewards.append(total_reward)
        lengths.append(info.get("length", 0))
        crashes.append(int(crashed))
        lane_changes.append(ep_lane_changes)
        high_speed_steps.append(ep_high_speed)
        idle_steps.append(ep_idle)
        all_avg_confs.append(np.mean(confidences) if confidences else 0.0)
        print(f"Episode {ep+1}: Avg Conf {all_avg_confs[-1]:.3f}")

    eval_env.close()

    overall_conf = np.mean(all_avg_confs)
    print(f"\nSummary for {model_name}")
    print(f"Avg Confidence: {overall_conf:.3f}")
    print(f"Avg Reward:     {np.mean(rewards):.2f} ± {np.std(rewards):.2f}")
    print(f"Crash Rate:     {np.sum(crashes)}/{num_eval_episodes} = {np.mean(crashes):.2f}")
    if safe_policy and hasattr(policy, "override_log"):
        print("\nSafe Overrides Summary:")
        for i, entry in enumerate(policy.override_log, start=1):
            if len(entry) == 4:
                step, conf, orig, override = entry
            elif len(entry) == 3:
                step, conf, override = entry
            elif len(entry) == 2:
                conf, override = entry
            else:
                continue
        print(f"Total Safe Overrides: {len(policy.override_log)}")
    print("=" * 60)

hard_highway_config = {
    "observation": {"type": "Kinematics"},
    "action": {"type": "DiscreteMetaAction"},
    "lanes_count": 4,
    "vehicles_count": 50,
    "duration": 40,
    "policy_frequency": 10,
    "simulation_frequency": 30,
    "vehicles_density": 1.0,
    "controlled_vehicles": 1,
    "other_vehicles_type": "highway_env.vehicle.behavior.AggressiveVehicle",
    "collision_reward": -10,
    "lane_change_reward": -0.2,
    "reward_speed_range": [25, 35],
    "normalize_reward": False,
    "screen_width": 800,
    "screen_height": 200,
    "scaling": 5.0,
    "centering_position": [0.3, 0.5],
    "render_agent": True,
    "offscreen_rendering": True,
    "show_trajectories": False,
    "right_lane_reward": 0.3,
    "high_speed_reward": 1.0
}

# PPO Baseline
train_and_evaluate(
    env_id="highway-fast-v0",
    model_name="ppo_baseline",
    log_subdir="./ppo_logs/ppo_baseline/",
    video_subdir="./ppo_videos/ppo_baseline/",
    noise=False,
    intention=False,
    safe_policy=False,
    skill_abstraction=False
)

# With Noise only
train_and_evaluate(
    env_id="highway-fast-v0",
    model_name="ppo_noise",
    log_subdir="./ppo_logs/ppo_noise/",
    video_subdir="./ppo_videos/ppo_noise/",
    noise=True,
    noise_level=0.5,
    intention=False,
    safe_policy=False,
    skill_abstraction=False
)

# With Noise + Intention
train_and_evaluate(
    env_id="highway-fast-v0",
    model_name="ppo_noise_intent",
    log_subdir="./ppo_logs/ppo_noise_intent/",
    video_subdir="./ppo_videos/ppo_noise_intent/",
    noise=True,
    noise_level=0.5,
    intention=True,
    safe_policy=False,
    skill_abstraction=False
)

# With Noise + Safety Overrides
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

# With Noise + Safety Overrides + Skill Abstraction
train_and_evaluate(
    env_id="highway-fast-v0",
    model_name="ppo_noise_safe_skill",
    log_subdir="./ppo_logs/ppo_noise_safe_skill/",
    video_subdir="./ppo_videos/ppo_noise_safe_skill/",
    noise=True,
    noise_level=0.5,
    intention=False,
    safe_policy=True,
    skill_abstraction=True
)

hard_roundabout_config = {
    "observation": {"type": "Kinematics"},
    "action": {"type": "DiscreteMetaAction"},
    "lanes_count": 1,
    "vehicles_count": 30,
    "controlled_vehicles": 1,
    "duration": 60,
    "policy_frequency": 15,
    "simulation_frequency": 15,
    "vehicles_density": 1.0,
    "other_vehicles_type": "highway_env.vehicle.behavior.AggressiveVehicle",
    "collision_reward": -5,
    "lane_change_reward": -0.1,
    "reward_speed_range": [20, 30],
    "normalize_reward": False,
    "screen_width": 600,
    "screen_height": 600,
    "centering_position": [0.5, 0.5],
    "scaling": 5.5,
    "show_trajectories": False,
    "render_agent": True,
    "offscreen_rendering": False
}

# PPO Baseline
train_and_evaluate(
    env_id="roundabout-v0",
    model_name="ppo_roundabout_baseline",
    log_subdir="./ppo_logs/roundabout_baseline/",
    video_subdir="./ppo_videos/roundabout_baseline/",
    noise=False,
    intention=False,
    safe_policy=False,
    skill_abstraction=False,
    env_config=hard_roundabout_config
)

# With Noise only
train_and_evaluate(
    env_id="roundabout-v0",
    model_name="ppo_roundabout_noise",
    log_subdir="./ppo_logs/roundabout_noise/",
    video_subdir="./ppo_videos/roundabout_noise/",
    noise=True,
    noise_level=0.2,
    intention=False,
    safe_policy=False,
    skill_abstraction=False,
    env_config=hard_roundabout_config
)

# With Noise + Intention
train_and_evaluate(
    env_id="roundabout-v0",
    model_name="ppo_roundabout_noise_intent",
    log_subdir="./ppo_logs/roundabout_noise_intent/",
    video_subdir="./ppo_videos/roundabout_noise_intent/",
    noise=True,
    noise_level=0.2,
    intention=True,
    safe_policy=False,
    skill_abstraction=False,
    env_config=hard_roundabout_config
)

# With Noise + Safety Overrides
train_and_evaluate(
    env_id="roundabout-v0",
    model_name="ppo_roundabout_noise_safe",
    log_subdir="./ppo_logs/roundabout_noise_safe/",
    video_subdir="./ppo_videos/roundabout_noise_safe/",
    noise=True,
    noise_level=0.2,
    intention=False,
    safe_policy=True,
    skill_abstraction=False,
    env_config=hard_roundabout_config
)

# With Noise + Safety Overrides + Skill Abstraction
train_and_evaluate(
    env_id="roundabout-v0",
    model_name="ppo_roundabout_noise_safe_skill",
    log_subdir="./ppo_logs/roundabout_noise_safe_skill/",
    video_subdir="./ppo_videos/roundabout_noise_safe_skill/",
    noise=True,
    noise_level=0.2,
    intention=False,
    safe_policy=True,
    skill_abstraction=True,
    env_config=hard_roundabout_config
)