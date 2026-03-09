import json
import os
import random
from dataclasses import dataclass
from typing import Optional

try:
    import jsonschema
    _JSONSCHEMA_AVAILABLE = True
except ImportError:
    _JSONSCHEMA_AVAILABLE = False


@dataclass
class Stimulus:
    stimulus_id:        str            # PlancheID
    task_type:          str
    payload:            dict           # canonical: files, positions, labels, correct index, etc.

    # Optional convenience fields (may duplicate payload entries)
    image_paths:        Optional[list] = None
    correct_response:   Optional[str] = None
    left_right_balance: Optional[str] = None

    is_excluded:        bool = False
    is_familiar:        Optional[bool] = None


class StimulusSet:
    """Ordered, iterable collection of stimuli for a session."""

    def __init__(self, stimuli: list):
        self._stimuli: list[Stimulus] = stimuli
        self._index: int = 0

    @property
    def current(self) -> Optional[Stimulus]:
        if self._index < len(self._stimuli):
            return self._stimuli[self._index]
        return None

    @property
    def is_exhausted(self) -> bool:
        return self._index >= len(self._stimuli)

    def advance(self) -> None:
        self._index += 1

    def __len__(self) -> int:
        return len(self._stimuli)

    def __iter__(self):
        return iter(self._stimuli)


# ---------------------------------------------------------------------------
# Counterbalancing result types
# ---------------------------------------------------------------------------

class CounterbalancingViolation:
    """One failed counterbalancing rule."""
    def __init__(self, rule: str, message: str):
        self.rule = rule
        self.message = message

    def __repr__(self) -> str:
        return f"[{self.rule}] {self.message}"


class CounterbalancingReport:
    """Full validation report for a StimulusSet."""

    def __init__(self):
        self.violations: list[CounterbalancingViolation] = []
        self.warnings: list[str] = []

    @property
    def is_valid(self) -> bool:
        return len(self.violations) == 0

    def add_violation(self, rule: str, message: str) -> None:
        self.violations.append(CounterbalancingViolation(rule, message))

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    def __repr__(self) -> str:
        if self.is_valid:
            lines = ["CounterbalancingReport: OK"]
        else:
            lines = [f"CounterbalancingReport: {len(self.violations)} violation(s)"]
            for v in self.violations:
                lines.append(f"  VIOLATION {v}")
        for w in self.warnings:
            lines.append(f"  WARNING   {w}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# StimulusLibrary
# ---------------------------------------------------------------------------

class StimulusLibrary:
    """Loads, validates, and manages all available stimuli from a directory."""

    def __init__(self):
        self._stimuli: dict[str, Stimulus] = {}

    # ------------------------------------------------------------------ #
    # Loading                                                              #
    # ------------------------------------------------------------------ #

    def load_from_directory(
        self,
        directory: str,
        task_type: str,
        schema_path: Optional[str] = None,
    ) -> None:
        """
        Load stimuli from JSON descriptor files in a directory.

        If schema_path is provided and jsonschema is installed, each file is
        validated against the JSON Schema before being added to the library.
        Invalid files raise jsonschema.ValidationError immediately.
        """
        schema = None
        if schema_path is not None:
            if not _JSONSCHEMA_AVAILABLE:
                import warnings
                warnings.warn(
                    "jsonschema is not installed; schema validation skipped. "
                    "Install with: pip install jsonschema",
                    stacklevel=2,
                )
            else:
                with open(schema_path, "r", encoding="utf-8") as f:
                    schema = json.load(f)

        for filename in sorted(os.listdir(directory)):
            if not filename.endswith(".json"):
                continue
            path = os.path.join(directory, filename)
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if schema is not None and _JSONSCHEMA_AVAILABLE:
                jsonschema.validate(instance=data, schema=schema)

            stimulus = Stimulus(
                stimulus_id=data["stimulus_id"],
                task_type=task_type,
                payload=data.get("payload", {}),
                image_paths=data.get("image_paths"),
                correct_response=data.get("correct_response"),
                left_right_balance=data.get("left_right_balance"),
                is_excluded=data.get("is_excluded", False),
                is_familiar=data.get("is_familiar"),
            )
            self._stimuli[stimulus.stimulus_id] = stimulus

    def add(self, stimulus: Stimulus) -> None:
        """Register a stimulus directly (e.g. for testing or programmatic construction)."""
        self._stimuli[stimulus.stimulus_id] = stimulus

    def get(self, stimulus_id: str) -> Optional[Stimulus]:
        return self._stimuli.get(stimulus_id)

    # ------------------------------------------------------------------ #
    # Set building                                                         #
    # ------------------------------------------------------------------ #

    def build_set(
        self,
        included: Optional[list] = None,
        excluded: Optional[list] = None,
        randomize: bool = False,
    ) -> StimulusSet:
        """Build a StimulusSet applying inclusion/exclusion filters."""
        stimuli = list(self._stimuli.values())

        if included:
            stimuli = [s for s in stimuli if s.stimulus_id in included]
        if excluded:
            stimuli = [s for s in stimuli if s.stimulus_id not in excluded]

        stimuli = [s for s in stimuli if not s.is_excluded]

        if randomize:
            random.shuffle(stimuli)

        return StimulusSet(stimuli)

    # ------------------------------------------------------------------ #
    # Counterbalancing validation                                          #
    # ------------------------------------------------------------------ #

    def check_counterbalancing(
        self,
        stim_set: StimulusSet,
        rules_path: Optional[str] = None,
    ) -> CounterbalancingReport:
        """
        Validate a StimulusSet against counterbalancing rules.

        If rules_path is provided, rules are loaded from the JSON file.
        Otherwise a built-in default rule set is applied.

        Returns a CounterbalancingReport; call .is_valid to test pass/fail.
        """
        stimuli = list(stim_set)
        if not stimuli:
            report = CounterbalancingReport()
            report.add_violation("set_size", "Stimulus set is empty.")
            return report

        task_type = stimuli[0].task_type
        rules = self._load_rules(rules_path, task_type)
        report = CounterbalancingReport()

        self._check_set_size(stimuli, rules, report)

        if task_type == "SemanticMatching":
            self._check_left_right_balance(stimuli, rules, report)
            self._check_category_coverage(
                stimuli, rules, report,
                field_getter=lambda s: s.payload.get("semantic_category"),
                rule_key="category_coverage",
            )

        elif task_type == "FamousFace":
            self._check_category_coverage(
                stimuli, rules, report,
                field_getter=lambda s: s.payload.get("person_category"),
                rule_key="category_coverage",
            )

        elif task_type == "UnknownFace":
            self._check_fractional_balance(
                stimuli, rules, report,
                field_getter=lambda s: s.payload.get("age_group"),
                rule_key="age_group_balance",
                label="age_group",
            )
            self._check_fractional_balance(
                stimuli, rules, report,
                field_getter=lambda s: s.payload.get("gender_presentation"),
                rule_key="gender_presentation_balance",
                label="gender_presentation",
                values_of_interest=["masculine", "feminine"],
            )

        return report

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _load_rules(rules_path: Optional[str], task_type: str) -> dict:
        """Load rules dict for the given task type from file or defaults."""
        _DEFAULTS = {
            "SemanticMatching": {
                "set_size": {"min": 20, "recommended": 30},
                "left_right_balance": {"min_fraction_each": 0.40, "max_fraction_each": 0.60},
                "category_coverage": {"min_planches_per_category": 2},
            },
            "FamousFace": {
                "set_size": {"min": 10, "recommended": 20},
                "category_coverage": {"min_planches_per_category": 2},
            },
            "UnknownFace": {
                "set_size": {"min": 10, "recommended": 20},
                "age_group_balance": {
                    "values": ["young", "middle-aged", "older"],
                    "min_fraction_each": 0.20,
                },
                "gender_presentation_balance": {
                    "values": ["masculine", "feminine"],
                    "min_fraction_each": 0.30,
                },
            },
        }
        if rules_path is not None:
            with open(rules_path, "r", encoding="utf-8") as f:
                all_rules = json.load(f)
            return all_rules.get(task_type, {})
        return _DEFAULTS.get(task_type, {})

    @staticmethod
    def _check_set_size(stimuli, rules, report):
        size_rule = rules.get("set_size", {})
        n = len(stimuli)
        minimum = size_rule.get("min", 0)
        recommended = size_rule.get("recommended", minimum)
        if n < minimum:
            report.add_violation(
                "set_size",
                f"Set has {n} planches; minimum required is {minimum}.",
            )
        elif n < recommended:
            report.add_warning(
                f"Set has {n} planches; recommended minimum is {recommended}."
            )

    @staticmethod
    def _check_left_right_balance(stimuli, rules, report):
        rule = rules.get("left_right_balance", {})
        n = len(stimuli)
        if n == 0:
            return
        left_count = sum(1 for s in stimuli if s.left_right_balance == "left")
        right_count = n - left_count
        left_frac = left_count / n
        right_frac = right_count / n
        min_frac = rule.get("min_fraction_each", 0.40)
        max_frac = rule.get("max_fraction_each", 0.60)
        if left_frac < min_frac or left_frac > max_frac:
            report.add_violation(
                "left_right_balance",
                f"Left responses: {left_count}/{n} ({left_frac:.0%}). "
                f"Required: {min_frac:.0%}–{max_frac:.0%} per side.",
            )

    @staticmethod
    def _check_category_coverage(stimuli, rules, report, field_getter, rule_key):
        rule = rules.get(rule_key, {})
        min_per = rule.get("min_planches_per_category", 2)
        counts: dict[str, int] = {}
        for s in stimuli:
            val = field_getter(s)
            if val is not None:
                counts[val] = counts.get(val, 0) + 1
        for category, count in counts.items():
            if count < min_per:
                report.add_violation(
                    rule_key,
                    f"Category '{category}' has only {count} planche(s); "
                    f"minimum is {min_per}.",
                )

    @staticmethod
    def _check_fractional_balance(
        stimuli, rules, report, field_getter, rule_key, label,
        values_of_interest: Optional[list] = None,
    ):
        rule = rules.get(rule_key, {})
        min_frac = rule.get("min_fraction_each", 0.20)
        n = len(stimuli)
        if n == 0:
            return
        values = values_of_interest or rule.get("values", [])
        counts: dict[str, int] = {}
        for s in stimuli:
            val = field_getter(s)
            if val is not None:
                counts[val] = counts.get(val, 0) + 1
        for v in values:
            frac = counts.get(v, 0) / n
            if frac < min_frac:
                report.add_violation(
                    rule_key,
                    f"{label}='{v}': {counts.get(v, 0)}/{n} ({frac:.0%}); "
                    f"minimum required is {min_frac:.0%}.",
                )
