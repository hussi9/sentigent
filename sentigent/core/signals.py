"""Signal Engine — computes operational signals from the gap between expectation and reality.

Signals are the core of Sentigent's judgment. They're computed from:
1. Agent's operational history (Layer 1)
2. Org-wide patterns (Layer 2)
3. Cross-customer baselines (Layer 3)
4. Domain profile defaults (cold start fallback)

NO LLM calls. Pure statistical computation. Must complete in <10ms.
"""

from __future__ import annotations

import math
from typing import Any

from sentigent.core.types import (
    BaselineStats,
    Profile,
    Signal,
    SignalType,
)


class SignalEngine:
    """Computes operational signals from context and baselines.

    The Signal Engine is the heart of Sentigent's judgment system.
    It produces five signals (caution, doubt, urgency, confidence, frustration)
    based on the gap between what the agent expects and what it observes.
    """

    def __init__(self, profile: Profile) -> None:
        self.profile = profile
        self.thresholds = profile.signal_thresholds

    def compute_all(
        self,
        task: str,
        context: dict[str, Any],
        agent_state: dict[str, Any],
        baselines: dict[str, BaselineStats],
        similar_episodes: list[dict[str, Any]] | None = None,
    ) -> list[Signal]:
        """Compute all five signals for a given evaluation context.

        Args:
            task: The task description
            context: Full decision context (customer info, amounts, etc.)
            agent_state: Current agent state (step, confidence, retries, etc.)
            baselines: Available statistical baselines (from all layers)
            similar_episodes: Past episodes similar to this one (from episodic memory)

        Returns:
            List of Signal objects with computed strengths
        """
        signals = [
            self._compute_caution(task, context, baselines),
            self._compute_doubt(context, agent_state, similar_episodes),
            self._compute_urgency(context, agent_state),
            self._compute_confidence(context, agent_state, baselines, similar_episodes),
            self._compute_frustration(agent_state),
        ]

        # Apply compound signal interactions (MOD 1.8)
        self._apply_compound_interactions(signals)

        return signals

    def _apply_compound_interactions(self, signals: list[Signal]) -> None:
        """Apply cross-signal interactions that model compound judgment effects.

        Real judgment considers interactions between signals:
        - High caution + high doubt = amplified caution (uncertainty makes anomalies scarier)
        - High urgency + low caution = boosted confidence (safe and time-sensitive → fast path)
        - High frustration + high doubt = amplified frustration (stuck AND uncertain → need help)
        - High confidence + low caution = reinforced confidence (known-good, no anomalies)

        Mutates signal strengths in-place. Interactions are bounded to [0.0, 1.0].
        """
        signal_map = {s.type: s for s in signals}
        caution = signal_map.get(SignalType.CAUTION)
        doubt = signal_map.get(SignalType.DOUBT)
        urgency = signal_map.get(SignalType.URGENCY)
        confidence = signal_map.get(SignalType.CONFIDENCE)
        frustration = signal_map.get(SignalType.FRUSTRATION)

        if not all([caution, doubt, urgency, confidence, frustration]):
            return

        # Interaction 1: Caution + Doubt → amplified caution
        # When both anomaly AND uncertainty are present, caution grows
        if caution.strength > 0.3 and doubt.strength > 0.3:
            boost = caution.strength * doubt.strength * 0.3  # Up to 7.5% boost
            caution.strength = min(1.0, round(caution.strength + boost, 3))
            if boost > 0.01:
                caution.contributing_factors.append(
                    f"Amplified by doubt ({doubt.strength:.2f}): anomaly + uncertainty"
                )

        # Interaction 2: Urgency + low caution → boosted confidence
        # Safe + time-sensitive = can proceed faster
        if urgency.strength > 0.5 and caution.strength < 0.2:
            boost = urgency.strength * 0.15  # Up to 15% confidence boost
            confidence.strength = min(1.0, round(confidence.strength + boost, 3))
            if boost > 0.01:
                confidence.contributing_factors.append(
                    f"Boosted by urgency ({urgency.strength:.2f}) with low risk"
                )

        # Interaction 3: Frustration + Doubt → amplified frustration
        # Stuck AND uncertain → stronger signal to change strategy
        if frustration.strength > 0.3 and doubt.strength > 0.3:
            boost = frustration.strength * doubt.strength * 0.25
            frustration.strength = min(1.0, round(frustration.strength + boost, 3))
            if boost > 0.01:
                frustration.contributing_factors.append(
                    f"Amplified by doubt ({doubt.strength:.2f}): stuck with uncertainty"
                )

        # Interaction 4: High confidence + low caution → reinforced confidence
        # Everything looks good → extra confidence
        if confidence.strength > 0.7 and caution.strength == 0.0 and doubt.strength < 0.2:
            boost = 0.05  # Small reinforcement
            confidence.strength = min(1.0, round(confidence.strength + boost, 3))
            confidence.contributing_factors.append("Reinforced: no anomalies, no doubt")

    def _compute_caution(
        self,
        task: str,
        context: dict[str, Any],
        baselines: dict[str, BaselineStats],
    ) -> Signal:
        """Caution signal: detects anomalies by comparing observed values to baselines.

        Fires when observed values deviate significantly from learned distributions.
        Two detection modes:
        1. Numeric: z-score computation against learned baselines
        2. Categorical: frequency-based rarity detection against learned distributions

        Signal strength is modulated by the profile's value hierarchy — safety-critical
        profiles produce stronger caution for the same anomaly.
        """
        max_z_score = 0.0
        contributing_factors: list[str] = []
        threshold = self.thresholds.get("caution_threshold", 2.0)

        # Check all numeric context values against baselines
        for key, value in context.items():
            if not isinstance(value, (int, float)):
                continue

            baseline = baselines.get(key)
            if baseline is None:
                continue

            z = baseline.z_score(value)
            if z > max_z_score:
                max_z_score = z

            if z > threshold:
                ratio = value / baseline.median if baseline.median > 0 else float("inf")
                contributing_factors.append(
                    f"{key}={value} is {ratio:.0f}x above baseline median ({baseline.median:.0f})"
                )

        # Check categorical context values for rare/unseen values
        categorical_anomaly = self._check_categorical_anomalies(
            context, baselines, contributing_factors,
        )

        # Combine numeric z-score and categorical anomaly (map categorical to z-score scale)
        combined_score = max(max_z_score, categorical_anomaly * threshold * 2)

        # Normalize to 0-1 range using smooth ramp
        if combined_score <= threshold:
            strength = 0.0
        else:
            # Smooth ramp: 0.0 at threshold, ~0.5 at 2x threshold, ~0.9 at 3x threshold
            normalized = (combined_score - threshold) / threshold
            strength = min(1.0, normalized / (1.0 + normalized))

        # Modulate by value hierarchy: safety-weighted profiles amplify caution (MOD 1.7)
        safety_weight = (
            self.profile.values.get_weight("safety")
            or self.profile.values.get_weight("financial_safety")
            or 0.5
        )
        if safety_weight > 0.7 and strength > 0:
            # Amplify caution for safety-critical profiles (up to 20% boost)
            strength = min(1.0, strength * (1.0 + (safety_weight - 0.7) * 0.67))

        reason = (
            f"Anomaly detected: {'; '.join(contributing_factors)}"
            if contributing_factors
            else "No significant anomalies detected"
        )

        return Signal(
            type=SignalType.CAUTION,
            strength=round(strength, 3),
            reason=reason,
            contributing_factors=contributing_factors,
        )

    @staticmethod
    def _check_categorical_anomalies(
        context: dict[str, Any],
        baselines: dict[str, BaselineStats],
        contributing_factors: list[str],
    ) -> float:
        """Check string/categorical context values for rare or unseen values.

        Uses frequency baselines stored with a "cat_" prefix convention.
        For categorical baselines:
          - sample_size = total observations seen
          - p5 = frequency threshold below which a value is considered "rare"
          - min_observed = frequency of the current value (0 if never seen)

        Returns a score from 0.0 (normal) to 1.0 (highly anomalous).
        """
        max_anomaly = 0.0

        for key, value in context.items():
            if not isinstance(value, str):
                continue

            # Look for categorical baseline named "cat_{key}"
            cat_baseline = baselines.get(f"cat_{key}")
            if cat_baseline is None:
                continue

            total_seen = cat_baseline.sample_size
            if total_seen < 10:
                continue  # Not enough data

            rare_threshold = cat_baseline.p5 if cat_baseline.p5 > 0 else 0.01
            value_frequency = cat_baseline.min_observed  # 0 = never seen

            if value_frequency < rare_threshold:
                anomaly_score = (
                    1.0 - (value_frequency / rare_threshold) if rare_threshold > 0 else 1.0
                )
                if anomaly_score > max_anomaly:
                    max_anomaly = anomaly_score
                    if value_frequency == 0:
                        contributing_factors.append(
                            f"{key}='{value}' has never been seen before (categorical anomaly)"
                        )
                    else:
                        contributing_factors.append(
                            f"{key}='{value}' is rare (frequency {value_frequency:.1%}, "
                            f"threshold {rare_threshold:.1%})"
                        )

        return max_anomaly

    def _compute_doubt(
        self,
        context: dict[str, Any],
        agent_state: dict[str, Any],
        similar_episodes: list[dict[str, Any]] | None = None,
    ) -> Signal:
        """Doubt signal: fires when compound confidence is low.

        Compound confidence = agent_confidence × data_quality × episode_match
        """
        agent_confidence = agent_state.get("confidence", 0.5)
        data_quality = context.get("data_quality", 0.8)
        threshold = self.thresholds.get("doubt_threshold", 0.6)

        # Episode match score: how well do past similar episodes match?
        episode_match = 1.0
        if similar_episodes is not None:
            if len(similar_episodes) == 0:
                episode_match = 0.5  # No similar episodes = some doubt
            else:
                # Check outcome consistency of similar episodes
                outcomes = [ep.get("outcome") for ep in similar_episodes if ep.get("outcome")]
                if outcomes:
                    correct_count = sum(1 for o in outcomes if o == "correct")
                    episode_match = correct_count / len(outcomes)

        compound_confidence = agent_confidence * data_quality * episode_match
        contributing_factors: list[str] = []

        if agent_confidence < 0.7:
            contributing_factors.append(f"Agent confidence low ({agent_confidence:.2f})")
        if data_quality < 0.7:
            contributing_factors.append(f"Data quality concern ({data_quality:.2f})")
        if episode_match < 0.7:
            contributing_factors.append(f"Similar past episodes had mixed outcomes ({episode_match:.2f})")

        if compound_confidence >= threshold:
            strength = 0.0
        else:
            strength = min(1.0, (threshold - compound_confidence) / threshold)

        reason = (
            f"Low compound confidence ({compound_confidence:.2f}): {'; '.join(contributing_factors)}"
            if contributing_factors
            else f"Confidence adequate ({compound_confidence:.2f})"
        )

        return Signal(
            type=SignalType.DOUBT,
            strength=round(strength, 3),
            reason=reason,
            contributing_factors=contributing_factors,
        )

    def _compute_urgency(
        self,
        context: dict[str, Any],
        agent_state: dict[str, Any],
    ) -> Signal:
        """Urgency signal: fires when time pressure + consequence severity is high.

        Reduces deliberation when delays have measurable consequences.
        Uses graduated ramp (not binary) for proportional urgency.
        """
        time_pressure = context.get("time_pressure", 0.0)
        consequence_severity = context.get("consequence_severity", 0.5)
        threshold = self.thresholds.get("urgency_threshold", 0.8)

        # Check for explicit urgency markers
        is_escalation = agent_state.get("is_escalation", False)
        has_deadline = context.get("deadline_minutes", None) is not None

        urgency_score = time_pressure * consequence_severity
        contributing_factors: list[str] = []

        if is_escalation:
            urgency_score = max(urgency_score, 0.7)
            contributing_factors.append("Active escalation in progress")

        if has_deadline:
            deadline_minutes = context["deadline_minutes"]
            if deadline_minutes < 5:
                urgency_score = max(urgency_score, 0.9)
                contributing_factors.append(f"Deadline in {deadline_minutes} minutes")
            elif deadline_minutes < 30:
                urgency_score = max(urgency_score, 0.6)
                contributing_factors.append(f"Deadline approaching ({deadline_minutes} min)")

        # Graduated ramp instead of binary threshold
        if urgency_score <= 0:
            strength = 0.0
        elif urgency_score >= threshold:
            strength = min(1.0, urgency_score)
        else:
            # Graduated ramp below threshold: moderate urgency still registers
            strength = urgency_score * 0.4

        reason = (
            f"Time-sensitive: {'; '.join(contributing_factors)}"
            if contributing_factors
            else "No time pressure detected"
        )

        return Signal(
            type=SignalType.URGENCY,
            strength=round(strength, 3),
            reason=reason,
            contributing_factors=contributing_factors,
        )

    def _compute_confidence(
        self,
        context: dict[str, Any],
        agent_state: dict[str, Any],
        baselines: dict[str, BaselineStats],
        similar_episodes: list[dict[str, Any]] | None = None,
    ) -> Signal:
        """Confidence signal: enables fast-path for routine operations.

        High confidence = this looks like a well-understood pattern with
        consistently good outcomes. Allows skipping extra validation.
        """
        threshold = self.thresholds.get("confidence_fast_path", 0.9)
        contributing_factors: list[str] = []

        # Factor 1: Agent's own confidence
        agent_confidence = agent_state.get("confidence", 0.5)

        # Factor 2: How "normal" are the values?
        normality_scores: list[float] = []
        for key, value in context.items():
            if not isinstance(value, (int, float)):
                continue
            baseline = baselines.get(key)
            if baseline is None:
                continue
            z = baseline.z_score(value)
            # Values within 1 std dev are very normal
            normality = max(0.0, 1.0 - (z / 3.0))
            normality_scores.append(normality)

        avg_normality = sum(normality_scores) / len(normality_scores) if normality_scores else 0.5

        # Factor 3: Similar episodes had good outcomes
        episode_confidence = 0.5
        if similar_episodes:
            correct = sum(1 for ep in similar_episodes if ep.get("outcome") == "correct")
            total = len(similar_episodes)
            if total >= 5:
                episode_confidence = correct / total
                contributing_factors.append(
                    f"Similar episodes: {correct}/{total} correct ({episode_confidence:.0%})"
                )

        # Adaptive weighting based on data availability
        has_episodes = similar_episodes and len(similar_episodes) >= 5
        has_baselines = len(normality_scores) > 0

        if has_episodes and has_baselines:
            w_agent, w_normal, w_episode = 0.25, 0.25, 0.50
        elif has_episodes:
            w_agent, w_normal, w_episode = 0.35, 0.15, 0.50
        elif has_baselines:
            w_agent, w_normal, w_episode = 0.45, 0.45, 0.10
        else:
            w_agent, w_normal, w_episode = 0.70, 0.20, 0.10

        strength = agent_confidence * w_agent + avg_normality * w_normal + episode_confidence * w_episode

        if strength >= threshold:
            contributing_factors.append("Pattern matches known-good outcomes")

        reason = (
            f"High confidence ({strength:.2f}): {'; '.join(contributing_factors)}"
            if strength >= threshold
            else f"Confidence moderate ({strength:.2f}), standard validation applies"
        )

        return Signal(
            type=SignalType.CONFIDENCE,
            strength=round(strength, 3),
            reason=reason,
            contributing_factors=contributing_factors,
        )

    def _compute_frustration(
        self,
        agent_state: dict[str, Any],
    ) -> Signal:
        """Frustration signal: triggers strategy change after repeated failures.

        Fires when retry count exceeds expectations, suggesting the current
        approach isn't working and a different strategy is needed.
        """
        retry_count = agent_state.get("retry_count", 0)
        max_retries = self.thresholds.get("frustration_retries", 3)
        contributing_factors: list[str] = []

        if retry_count >= max_retries:
            strength = min(1.0, retry_count / (max_retries * 2))
            contributing_factors.append(
                f"Attempt {retry_count} (max expected: {max_retries})"
            )
            if agent_state.get("last_error"):
                contributing_factors.append(f"Last error: {agent_state['last_error']}")
        else:
            strength = 0.0

        reason = (
            f"Strategy change needed: {'; '.join(contributing_factors)}"
            if contributing_factors
            else f"Attempt {retry_count}/{max_retries}, within normal range"
        )

        return Signal(
            type=SignalType.FRUSTRATION,
            strength=round(strength, 3),
            reason=reason,
            contributing_factors=contributing_factors,
        )
