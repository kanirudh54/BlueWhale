#!/usr/bin/env python3

import itertools
import logging
from collections import Counter
from typing import List

import numpy as np
import scipy as sp


logger = logging.getLogger(__name__)


class Evaluator(object):
    num_subsets_for_cb_estimate = 25

    def __init__(self, action_names, evaluator_batch_size, gamma) -> None:
        self.action_names = action_names
        self.mc_loss: List[float] = []
        self.td_loss: List[float] = []
        self.reward_loss: List[float] = []
        self.value_inverse_propensity_score: List[float] = []
        self.value_direct_method: List[float] = []
        self.value_doubly_robust: List[float] = []
        self.sequential_value_doubly_robust: List[float] = []
        self.weighted_sequential_value_doubly_robust: List[float] = []
        self.magic_value_doubly_robust: List[float] = []
        self.true_value_PE: List[float] = []
        self.true_discounted_value_PE: List[float] = []
        self.reward_inverse_propensity_score: List[float] = []
        self.reward_direct_method: List[float] = []
        self.reward_doubly_robust: List[float] = []

        self.evaluator_batch_size = evaluator_batch_size

        self.td_loss_batches: List[np.ndarray] = []
        self.logged_actions_batches: List[np.ndarray] = []
        self.logged_propensities_batches: List[np.ndarray] = []
        self.logged_rewards_batches: List[np.ndarray] = []
        self.logged_values_batches: List[np.ndarray] = []
        self.model_propensities_batches: List[np.ndarray] = []
        self.model_values_batches: List[np.ndarray] = []
        self.model_values_on_logged_actions_batches: List[np.ndarray] = []
        self.model_action_idxs_batches: List[np.ndarray] = []

        self.all_batches = [
            self.td_loss_batches,
            self.logged_actions_batches,
            self.logged_propensities_batches,
            self.logged_rewards_batches,
            self.logged_values_batches,
            self.model_propensities_batches,
            self.model_values_batches,
            self.model_values_on_logged_actions_batches,
            self.model_action_idxs_batches,
        ]

        self.gamma = gamma

    def report(
        self,
        td_loss,
        logged_actions,
        logged_propensities,
        logged_rewards,
        logged_values,
        model_propensities,
        model_values,
        model_values_on_logged_actions,
        model_action_idxs,
    ):
        input_list = [
            td_loss,
            logged_actions,
            logged_propensities,
            logged_rewards,
            logged_values,
            model_propensities,
            model_values,
            model_values_on_logged_actions,
            model_action_idxs,
        ]
        for i, input in enumerate(input_list):
            if input is None:
                assert (
                    len(self.all_batches[i]) == 0
                ), "Missing a batch.  Either omit completely or fill every time"
            else:
                self.all_batches[i].append(input)

        if len(self.td_loss_batches) >= self.evaluator_batch_size:
            self.evaluate_batch()
            self.clear_evaluation_containers()

    def clear_evaluation_containers(self):
        for batch in self.all_batches:
            batch.clear()

    def evaluate_batch(self):
        merged_inputs = []
        for batch in self.all_batches:
            if len(batch) > 0:
                merged_inputs.append(np.vstack(batch))
            else:
                merged_inputs.append(None)
        td_loss, logged_actions, logged_propensities, logged_rewards, logged_values, model_propensities, model_values, model_values_on_logged_actions, model_action_idxs = (
            merged_inputs
        )

        logger.info("Evaluating on {} batches".format(len(self.td_loss_batches)))
        print_details = "Evaluator:\n"
        if td_loss is not None:
            td_loss_mean = float(np.mean(td_loss))
            self.td_loss.append(td_loss_mean)
            print_details = print_details + "TD LOSS: {0:.3f}\n".format(td_loss_mean)
        if logged_values is not None:
            mc_loss = float(
                np.mean(np.abs(logged_values - model_values_on_logged_actions))
            )
            self.mc_loss.append(mc_loss)
            print_details = print_details + "MC LOSS: {0:.3f}\n".format(mc_loss)

        if (
            logged_actions is not None
            and model_propensities is not None
            and model_values is not None
        ):
            if logged_propensities is None:
                # Assume a deterministic model
                logged_propensities = np.ones(logged_values.shape)

            v_ips, v_dm, v_dr = self.doubly_robust_one_step_policy_estimation(
                logged_actions,
                logged_values,
                logged_propensities,
                model_propensities,
                model_values,
            )
            self.value_inverse_propensity_score.append(v_ips)
            self.value_direct_method.append(v_dm)
            self.value_doubly_robust.append(v_dr)

            print_details += "Value Inverse Propensity Score : {0:.3f}\n".format(v_ips)
            print_details += "Value Direct Method            : {0:.3f}\n".format(v_dm)
            print_details += "Value Doubly Robust P.E.       : {0:.3f}\n".format(v_dr)

            r_ips, r_dm, r_dr = self.doubly_robust_one_step_policy_estimation(
                logged_actions,
                logged_rewards,
                logged_propensities,
                model_propensities,
                None,
            )
            self.reward_inverse_propensity_score.append(r_ips)
            self.reward_direct_method.append(r_dm)
            self.reward_doubly_robust.append(r_dr)

            print_details += "Reward Inverse Propensity Score : {0:.3f}\n".format(r_ips)
            print_details += "Reward Direct Method            : {0:.3f}\n".format(r_dm)
            print_details += "Reward Doubly Robust P.E.       : {0:.3f}\n".format(r_dr)

        if logged_actions is not None and model_action_idxs is not None:
            logged_action_counter = Counter(np.argmax(logged_actions, axis=1))
            model_action_counter = Counter(model_action_idxs.reshape(-1))
            print_details += "The distribution of logged actions : {}\n".format(
                {
                    action_name: logged_action_counter[i]
                    for i, action_name in enumerate(self.action_names)
                }
            )
            print_details += "The distribution of model actions : {}\n".format(
                {
                    action_name: model_action_counter[i]
                    for i, action_name in enumerate(self.action_names)
                }
            )

        print_details += "Evaluator Finished"
        for print_detail in print_details.split("\n"):
            logger.info(print_detail)

    def get_recent_td_loss(self):
        begin = max(0, len(self.td_loss) - 100)
        return np.mean(np.array(self.td_loss[begin:]))

    def get_recent_mc_loss(self):
        begin = max(0, len(self.mc_loss) - 100)
        return np.mean(np.array(self.mc_loss[begin:]))

    def get_recent_inverse_propensity_score(self):
        begin = max(0, len(self.reward_inverse_propensity_score) - 100)
        return np.mean(np.array(self.reward_inverse_propensity_score[begin:]))

    def get_recent_direct_method(self):
        begin = max(0, len(self.reward_direct_method) - 100)
        return np.mean(np.array(self.reward_direct_method[begin:]))

    def get_recent_doubly_robust(self):
        begin = max(0, len(self.reward_doubly_robust) - 100)
        return np.mean(np.array(self.reward_doubly_robust[begin:]))

    def doubly_robust_one_step_policy_estimation(
        self,
        logged_actions,
        logged_rewards,
        logged_propensities,
        target_propensities,
        estimated_values,
    ):
        # For details, visit https://arxiv.org/pdf/1612.01205.pdf
        num_examples = len(logged_actions)

        if estimated_values is None:
            # Fill with zero, equivalent to just doing IPS
            estimated_values = np.zeros(target_propensities.shape)
            direct_method_values = np.zeros([num_examples, 1], dtype=np.float32)
        else:
            direct_method_values = np.sum(
                target_propensities * estimated_values, axis=1, keepdims=True
            )

        total_reward = np.sum(logged_rewards)

        target_propensity_for_action = np.sum(
            target_propensities * logged_actions, axis=1, keepdims=True
        )
        importance_weight = target_propensity_for_action / logged_propensities
        ips = importance_weight * logged_rewards
        estimated_values_for_action = np.sum(
            estimated_values * logged_actions, axis=1, keepdims=True
        )
        doubly_robust = (
            importance_weight * (logged_rewards - estimated_values_for_action)
        ) + direct_method_values

        return (
            float(np.sum(ips) / total_reward),
            float(np.sum(direct_method_values) / total_reward),
            float(np.sum(doubly_robust) / total_reward),
        )

    def doubly_robust_sequential_policy_estimation(
        self,
        logged_actions,
        logged_rewards,
        logged_is_terminals,
        logged_propensities,
        target_propensities,
        estimated_Q_values,
    ):
        # For details, visit https://arxiv.org/pdf/1511.03722.pdf
        num_examples = logged_actions.shape[0]

        direct_method_Q_values = np.sum(
            target_propensities * estimated_Q_values, axis=1, keepdims=True
        )

        target_propensity_for_action = np.sum(
            target_propensities * logged_actions, axis=1, keepdims=True
        )
        importance_weight = target_propensity_for_action / logged_propensities

        estimated_values_for_action = np.sum(
            estimated_Q_values * logged_actions, axis=1, keepdims=True
        )

        doubly_robusts = []

        i = 0
        last_episode_end = -1
        while i < num_examples:
            # calculate the doubly-robust Q-value for one episode
            if logged_is_terminals[i][0]:
                episode_end = i
                episode_value = 0.0
                doubly_robust = 0.0
                for j in range(episode_end, last_episode_end - 1, -1):
                    doubly_robust = direct_method_Q_values[j][0] + importance_weight[j][
                        0
                    ] * (
                        logged_rewards[j][0]
                        + self.gamma * doubly_robust
                        - estimated_values_for_action[j][0]
                    )
                    episode_value *= self.gamma
                    episode_value += logged_rewards[j][0]
                doubly_robusts.append(doubly_robust / episode_value)
                last_episode_end = episode_end
            i += 1
        return np.mean(doubly_robusts)

    def weighted_doubly_robust_sequential_policy_estimation(
        self,
        logged_actions,
        logged_rewards,
        logged_is_terminals,
        logged_propensities,
        target_propensities,
        estimated_Q_values,
        num_j_steps,
    ):
        # For details, visit https://arxiv.org/pdf/1604.00923.pdf Section 5, 7, 8
        (
            actions,
            rewards,
            logged_propensities,
            target_propensities,
            estimated_Q_values,
        ) = Evaluator.transform_to_equal_length_trajectories(
            logged_is_terminals.squeeze(),
            logged_actions,
            logged_rewards.squeeze(),
            logged_propensities.squeeze(),
            target_propensities,
            estimated_Q_values,
        )

        num_trajectories = actions.shape[0]
        trajectory_length = actions.shape[1]

        j_steps = [float("inf")]

        if num_j_steps > 1:
            j_steps.append(-1)
        if num_j_steps > 2:
            interval = trajectory_length // (num_j_steps - 1)
            j_steps.extend([i * interval for i in range(1, num_j_steps - 1)])

        target_propensity_for_logged_action = np.sum(
            np.multiply(target_propensities, actions), axis=2
        )
        estimated_Q_values_for_logged_action = np.sum(
            np.multiply(estimated_Q_values, actions), axis=2
        )
        estimated_state_values = np.sum(
            np.multiply(target_propensities, estimated_Q_values), axis=2
        )

        importance_weights = target_propensity_for_logged_action / logged_propensities
        importance_weights = Evaluator.normalize_importance_weights(importance_weights)

        importance_weights_one_earlier = (
            np.ones([num_trajectories, 1]) * 1.0 / num_trajectories
        )
        importance_weights_one_earlier = np.hstack(
            [importance_weights_one_earlier, importance_weights[:, 1:]]
        )

        discounts = np.logspace(
            start=0, stop=trajectory_length - 1, num=trajectory_length, base=self.gamma
        )

        weighted_discounts = np.multiply(discounts, importance_weights)
        weighted_discounts_one_earlier = np.multiply(
            discounts, importance_weights_one_earlier
        )

        j_step_return_trajectories = []
        for j_step in j_steps:
            j_step_return_trajectories.append(
                Evaluator.calculate_step_return(
                    weighted_discounts,
                    weighted_discounts_one_earlier,
                    rewards,
                    estimated_state_values,
                    estimated_Q_values_for_logged_action,
                    j_step,
                )
            )
        j_step_return_trajectories = np.array(j_step_return_trajectories)

        j_step_returns = np.sum(j_step_return_trajectories, axis=1)

        if len(j_step_returns) == 1:
            weighted_doubly_robust = j_step_returns[0]

        else:
            # break trajectories into 25 subsets to estimate confidence bounds
            infinite_step_returns = []
            interval = num_trajectories / Evaluator.num_subsets_for_cb_estimate
            for i in range(Evaluator.num_subsets_for_cb_estimate):
                trajectory_subset = np.arange(
                    int(i * interval), int((i + 1) * interval)
                )
                importance_weights = (
                    target_propensity_for_logged_action[trajectory_subset]
                    / logged_propensities[trajectory_subset]
                )
                importance_weights = Evaluator.normalize_importance_weights(
                    importance_weights
                )
                importance_weights_one_earlier = (
                    np.ones([len(trajectory_subset), 1]) * 1.0 / len(trajectory_subset)
                )
                importance_weights_one_earlier = np.hstack(
                    [importance_weights_one_earlier, importance_weights[:, 1:]]
                )
                infinite_step_return = np.sum(
                    Evaluator.calculate_step_return(
                        np.multiply(discounts, importance_weights),
                        np.multiply(discounts, importance_weights_one_earlier),
                        rewards[trajectory_subset],
                        estimated_state_values[trajectory_subset],
                        estimated_Q_values_for_logged_action[trajectory_subset],
                        float("inf"),
                    )
                )
                infinite_step_returns.append(infinite_step_return)

            low_bound, high_bound = Evaluator.confidence_interval(
                infinite_step_returns, 0.9
            )

            # decompose error into bias + variance
            j_step_bias = np.zeros([num_j_steps])
            where_lower = np.where(j_step_returns < low_bound)[0]
            j_step_bias[where_lower] = low_bound - j_step_returns[where_lower]
            where_higher = np.where(j_step_returns > high_bound)[0]
            j_step_bias[where_higher] = j_step_returns[where_higher] - high_bound

            covariance = np.cov(j_step_return_trajectories)

            error = covariance + j_step_bias.T * j_step_bias

            # minimize mse error
            def mse_loss(x, error):
                return np.dot(np.dot(x, error), x.T)

            constraint = {"type": "eq", "fun": lambda x: np.sum(x) - 1.0}

            x = np.zeros([len(j_steps)])
            res = sp.optimize.minimize(
                mse_loss,
                x,
                args=error,
                constraints=constraint,
                bounds=[(0, 1) for _ in range(x.shape[0])],
            )
            x = np.array(res.x)

            weighted_doubly_robust = np.dot(x, j_step_returns)

        episode_values = np.sum(np.multiply(rewards, discounts), axis=1)

        return weighted_doubly_robust / np.mean(episode_values)

    @staticmethod
    def normalize_importance_weights(importance_weights):
        sum_importance_weights = np.sum(importance_weights, axis=0)
        where_zeros = np.where(sum_importance_weights == 0.0)[0]
        sum_importance_weights[where_zeros] = len(importance_weights)
        importance_weights[:, where_zeros] = 1.0
        importance_weights /= sum_importance_weights
        return importance_weights

    @staticmethod
    def calculate_step_return(
        weighted_discounts,
        weighted_discounts_one_earlier,
        rewards,
        estimated_state_values,
        estimated_Q_values,
        j_step,
    ):
        trajectory_length = len(rewards[0])
        num_trajectories = len(rewards)
        j_step = int(min(j_step, trajectory_length - 1))

        importance_sampled_cumulative_reward = np.sum(
            np.multiply(weighted_discounts[:, : j_step + 1], rewards[:, : j_step + 1]),
            axis=1,
        )

        if j_step < trajectory_length - 1:
            direct_method_value = (
                weighted_discounts_one_earlier[:, j_step + 1]
                * estimated_state_values[:, j_step + 1]
            )
        else:
            direct_method_value = np.zeros([num_trajectories])

        control_variate = np.sum(
            np.multiply(
                weighted_discounts[:, : j_step + 1], estimated_Q_values[:, : j_step + 1]
            )
            - np.multiply(
                weighted_discounts_one_earlier[:, : j_step + 1],
                estimated_state_values[:, : j_step + 1],
            ),
            axis=1,
        )

        j_step_return = (
            importance_sampled_cumulative_reward + direct_method_value - control_variate
        )
        return j_step_return

    @staticmethod
    def confidence_interval(x, confidence):
        n = len(x)
        m, se = np.mean(x), sp.stats.sem(x)
        h = se * sp.stats.t._ppf((1 + confidence) / 2.0, n - 1)
        return m - h, m + h

    @staticmethod
    def transform_to_equal_length_trajectories(
        is_terminals,
        actions,
        rewards,
        logged_propensities,
        target_propensities,
        estimated_Q_values,
    ):
        """
        Take into samples (action, rewards, propensities, etc.) and output lists
        of equal-length trajectories (episodes) accoriding to is_terminalsself.
        As the raw trajectories are of various lengths, the shorter ones are
        filled with zeros(ones) at the end.
        """
        num_actions = len(target_propensities[0])

        trajectories = []
        episode_start = 0
        episode_ends = np.nonzero(is_terminals)[0]
        for episode_end in episode_ends:
            trajectories.append(np.arange(episode_start, episode_end + 1))
            episode_start = episode_end + 1

        action_trajectories = []
        reward_trajectories = []
        logged_propensity_trajectories = []
        target_propensity_trajectories = []
        Q_value_trajectories = []

        for trajectory in trajectories:
            action_trajectories.append(actions[trajectory])
            reward_trajectories.append(rewards[trajectory])
            logged_propensity_trajectories.append(logged_propensities[trajectory])
            target_propensity_trajectories.append(target_propensities[trajectory])
            Q_value_trajectories.append(estimated_Q_values[trajectory])

        def to_equal_length(x, fill_value):
            x_equal_length = np.array(
                list(itertools.zip_longest(*x, fillvalue=fill_value))
            ).swapaxes(0, 1)
            return x_equal_length

        action_trajectories = to_equal_length(
            action_trajectories, np.zeros([num_actions])
        )
        reward_trajectories = to_equal_length(reward_trajectories, 0)
        logged_propensity_trajectories = to_equal_length(
            logged_propensity_trajectories, 1
        )
        target_propensity_trajectories = to_equal_length(
            target_propensity_trajectories, np.zeros([num_actions])
        )
        Q_value_trajectories = to_equal_length(
            Q_value_trajectories, np.zeros([num_actions])
        )

        return (
            action_trajectories,
            reward_trajectories,
            logged_propensity_trajectories,
            target_propensity_trajectories,
            Q_value_trajectories,
        )

    @staticmethod
    def softmax(x, temperature):
        """Compute softmax values for each sets of scores in x."""
        x = x / temperature
        x -= np.max(x, axis=1, keepdims=True)
        e_x = np.exp(x)
        return e_x / e_x.sum(axis=1, keepdims=True)

    @staticmethod
    def huberLoss(label, output):
        if abs(label - output) > 1:
            return abs(label - output) - 0.5
        else:
            return 0.5 * (label - output) * (label - output)
