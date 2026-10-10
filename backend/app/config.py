"""Central configuration. Research-critical constants live here, not in route code."""

from dataclasses import asdict, dataclass, field

APP_NAME = "PigmentCal-UQ"
APP_VERSION = "1.0.0"
DISCLAIMER = "Not a diagnostic device — not for medical diagnosis."

SIGNAL_LEVELS = ("GOOD", "MODERATE", "POOR")
MOTION_LEVELS = ("LOW", "MEDIUM", "HIGH")
# Acquisition devices / sources the reliability layer can assess.
DEVICES = ("ESP32 + MAX30102", "Virtual ESP32 + Virtual MAX30102 (simulation)", "Phone camera", "Recorded file", "Other")


@dataclass(frozen=True)
class ReliabilityConfig:
    """Rule thresholds for the transparent reliability engine.

    These are configurable default settings — NOT clinical thresholds and NOT learned. A calibrated
    uncertainty range (CQR / ITA x PI Mondrian) requires a real dataset and is not produced until
    one has been loaded and calibrated; until then the engine reports a state and reasons only.
    """

    # Supported input ranges
    spo2_min: float = 70.0
    spo2_max: float = 100.0
    pi_max: float = 20.0
    ita_min: float = -90.0
    ita_max: float = 90.0

    # Objective pigmentation categories from ITA (degrees). Cut-offs adapted from commonly cited
    # ITA bands; ITA is a colorimetric descriptor, not race.
    # NOTE: 'Light' / 'Medium' / 'Dark' are only labels of these configured bands. They are NOT the standard ITA skin-tone categories
    # (very light >55, light 41-55, intermediate 28-41, tan 10-28, brown -30-10, dark <-30); 'Dark' (ITA <= 10) is not 'the darkest skin'.
    ita_light_above: float = 41.0   # ITA > 41      -> Light
    ita_dark_at_most: float = 10.0  # ITA <= 10     -> Dark; otherwise Medium

    # Perfusion index (%) thresholds — not clinically validated
    pi_low_below: float = 1.0
    pi_very_low_below: float = 0.5

    # Degradation points: each concurrent condition adds points; the total sets the state.
    points_low_pi: int = 1
    points_very_low_pi: int = 2
    points_moderate_signal: int = 1
    points_medium_motion: int = 1
    red_points: int = 3  # >= this -> RED; any points -> AMBER; none -> GREEN (POOR signal / HIGH motion -> ABSTAIN)

    def as_dict(self) -> dict:
        return asdict(self)


RELIABILITY_CONFIG = ReliabilityConfig()


@dataclass(frozen=True)
class SignalConfig:
    """PPG processing settings. SQI weights/thresholds are default values, not clinically validated."""

    fs_min: float = 20.0
    fs_max: float = 1000.0
    min_seconds: float = 5.0
    max_samples: int = 60000
    max_invalid_fraction: float = 0.2

    # Band-pass (Hz): removes baseline drift (<0.5) and high-frequency noise (>5)
    band_low: float = 0.5
    band_high: float = 5.0
    filter_order: int = 2

    # Pulse detection: max 200 bpm -> min peak distance 0.3 s
    min_peak_distance_s: float = 0.3
    peak_prominence_std: float = 0.3  # prominence >= this x std(filtered)
    pulse_rate_min: float = 30.0
    pulse_rate_max: float = 220.0

    # SQI component normalisation (value giving a full / zero component score)
    skew_full: float = 0.6        # skewness >= this -> skew score 1
    hf_ratio_zero: float = 1.0    # high-freq/in-band power ratio >= this -> noise score 0
    amp_cv_zero: float = 0.5      # beat-amplitude CV >= this -> amplitude score 0
    ibi_cv_zero: float = 0.25     # inter-beat-interval CV >= this -> regularity score 0
    weights: dict = field(default_factory=lambda: {"skewness": 0.25, "noise": 0.25, "amplitude": 0.2, "regularity": 0.3})

    # Default SQI thresholds (0-100) - not clinically validated
    sqi_good_min: float = 70.0
    sqi_moderate_min: float = 40.0

    # Motion estimate from 1-s window amplitude outliers (no accelerometer yet)
    motion_window_s: float = 1.0
    motion_outlier_factor: float = 2.0
    motion_fraction_full: float = 0.4   # outlier-window fraction mapping to score 100
    motion_low_below: float = 25.0
    motion_high_from: float = 60.0

    def as_dict(self) -> dict:
        return asdict(self)


SIGNAL_CONFIG = SignalConfig()


LOCATIONS = ("Finger dorsal", "Finger palmar", "Forehead", "Other")
NOT_SPECIFIED = "Not specified"


@dataclass(frozen=True)
class PigmentationConfig:
    """Colorimetry limits and warnings. The Light/Medium/Dark ITA cut-offs live in
    ReliabilityConfig (ita_light_above / ita_dark_at_most) so there is one source of truth."""

    L_min: float = 0.0
    L_max: float = 100.0
    ab_min: float = -128.0
    ab_max: float = 127.0
    repeat_spread_warn_deg: float = 15.0  # max-min ITA across repeats that triggers a warning (configured value)

    def as_dict(self) -> dict:
        return asdict(self)


PIGMENTATION_CONFIG = PigmentationConfig()


@dataclass(frozen=True)
class PerfusionConfig:
    """Perfusion warning limits. The Low/Normal PI thresholds live in ReliabilityConfig
    (pi_low_below / pi_very_low_below / pi_max) so there is one source of truth.
    All values are configured settings, not clinically validated."""

    pi_typical_high: float = 10.0   # PI above this (%) triggers an 'unusual value' warning
    dc_tiny: float = 1e-6           # DC_IR below this triggers an 'extremely small DC' warning

    def as_dict(self) -> dict:
        return asdict(self)


PERFUSION_CONFIG = PerfusionConfig()
PI_THRESHOLD_LABEL = "Configured threshold — not clinically validated."


@dataclass(frozen=True)
class ModelConfig:
    """Model-training settings. Hyperparameters are tuned ONLY by participant-grouped
    cross-validation on the training split — never on calibration or test data."""

    seed: int = 42
    cv_folds: int = 5
    ridge_alphas: tuple = (0.01, 0.1, 1.0, 10.0, 100.0)
    lgbm_num_leaves: tuple = (4, 8, 16)
    lgbm_n_estimators: tuple = (100, 300)
    lgbm_learning_rate: float = 0.05
    lgbm_min_child_samples: int = 10
    # A subgroup with fewer test participants than this is flagged as low-n (still reported, never hidden)
    min_subgroup_participants: int = 5

    def as_dict(self) -> dict:
        return asdict(self)


MODEL_CONFIG = ModelConfig()


@dataclass(frozen=True)
class LiveConfig:
    """Real-time acquisition settings (ESP32 + MAX30102, camera PPG, recorded files)."""

    window_seconds: float = 10.0       # rolling analysis window
    min_window_seconds: float = 6.0    # do not analyze less than this
    analysis_interval_s: float = 1.0   # how often the client requests a new analysis
    max_samples: int = 20000
    resample_fs_max: float = 200.0
    # Ratio-of-ratios SpO2 estimate: SpO2 = a*R^2 + b*R + c. These are the generic empirical
    # coefficients used in public MAX3010x example code. They are NOT calibrated to your hardware
    # and the result is a research estimate, never a measurement.
    spo2_poly: tuple = (-45.060, 30.354, 94.845)
    spo2_note: str = "Uncalibrated ratio-of-ratios estimate (generic coefficients) — research estimate, not a measurement."
    # Signal polarity: reflective PPG sensors usually report LOWER values at systole, so the signal is flipped
    invert_default: dict = field(default_factory=lambda: {"esp32": True, "virtual": True, "camera": True, "file": False})
    # Accelerometer motion (units of g): std of |a| over the window
    accel_low_below_g: float = 0.03
    accel_high_from_g: float = 0.12

    def as_dict(self) -> dict:
        return asdict(self)


LIVE_CONFIG = LiveConfig()


@dataclass(frozen=True)
class PipelineConfig:
    """Dataset ingestion, cleaning and participant-level splitting."""

    seed: int = 42
    train_fraction: float = 0.6
    calibration_fraction: float = 0.2     # test gets the remainder
    min_participants: int = 10            # fewer cannot be split into train / calibration / test sensibly
    sat_min: float = 50.0                 # valid range for SpO2 and SaO2 (%)
    sat_max: float = 100.0
    max_upload_mb: int = 300

    def as_dict(self) -> dict:
        return asdict(self)


PIPELINE_CONFIG = PipelineConfig()


@dataclass(frozen=True)
class CollectionConfig:
    """Own-data collection: staging uploads, matching them, and building the research dataset."""

    hop_seconds: float = 5.0            # PPG analysis windows: LiveConfig.window_seconds long, advancing by this step
    match_tolerance_s: float = 30.0     # a reference SaO2 is paired with the nearest PPG window ending within this many seconds
    # LIMITATION: 30 s is a generous default (keeps few readings unmatched) but true SaO2 can change within it; tighten it for protocols with simultaneous sampling.
    ita_consistency_tol_deg: float = 1.0  # warn if a supplied ITA differs from the one computed from L*, a*, b*
    max_upload_mb: int = 200
    max_upload_rows: int = 2_000_000    # a CSV with more data rows than this is refused (memory / denial-of-service guard)
    max_listed: int = 200               # unmatched records listed in the report (counts are always complete)
    min_training_participants: int = 10  # model training stays blocked below this many valid participants
    id_pattern: str = r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}$"

    def as_dict(self) -> dict:
        return asdict(self)


COLLECTION_CONFIG = CollectionConfig()
CONSENT_NOTICE = ("Store participant data securely and obtain appropriate consent/ethics approval "
                  "before real human data collection.")


@dataclass(frozen=True)
class ConformalConfig:
    """Conformalized quantile regression (CQR) with Mondrian (ITA group x PI group) calibration.

    Every number is a configured default setting — not clinical and not learned from data. The procedure targets
    coverage 1 - alpha under its calibration assumptions; it is NOT a probability statement about one person."""

    alpha: float = 0.10                  # miscoverage: target coverage 90 %
    # A cell is calibrated on its OWN calibration data only if it has enough participants AND rows; readings from
    # the same participant are correlated, so participants (not just rows) must be sufficient.
    min_cell_participants: int = 10
    min_cell_rows: int = 30
    # Documented merge rule for an insufficient cell: pool the two PI cells of the SAME ITA group ("ita_group"),
    # or never merge ("none"). A merged cell is flagged MERGED and is not a per-cell guarantee. No other pooling is done.
    merge_rule: str = "ita_group"
    min_test_participants: int = 5       # test groups with fewer participants are flagged "low n" in the coverage tables
    # Quantile models: LightGBM quantile regression, tuned by participant-grouped CV on the TRAIN split only (pinball loss)
    cv_folds: int = 5
    lgbm_num_leaves: tuple = (4, 8)
    lgbm_n_estimators: tuple = (100, 300)
    lgbm_learning_rate: float = 0.05
    lgbm_min_child_samples: int = 10
    seed: int = 42
    # Reliability-state thresholds (percentage points of SaO2). Configured, not clinical.
    width_amber: float = 4.0             # interval wider than this -> at least AMBER
    width_red: float = 8.0               # ... wider than this -> RED
    gap_amber: float = 3.0               # reading exceeds the conformal LOWER bound by more than this -> at least AMBER
    gap_red: float = 5.0                 # ... by more than this -> RED

    def as_dict(self) -> dict:
        return asdict(self)


CONFORMAL_CONFIG = ConformalConfig()
COVERAGE_WORDING = ("The calibrated procedure targets the stated coverage under the calibration assumptions "
                    "(calibration and new readings are exchangeable within the calibration cell). It is not a probability that this "
                    "individual's value lies in the interval, and it is not clinically validated.")


@dataclass(frozen=True)
class ValidationConfig:
    """Statistical validation on the TEST split: participant-level (cluster) percentile bootstrap."""

    bootstrap_reps: int = 2000
    seed: int = 42
    level: float = 0.95
    min_ci_participants: int = 10      # fewer test participants -> no CI is reported (never fabricated)
    plot_max_points: int = 800
    hist_bins: int = 20

    def as_dict(self) -> dict:
        return asdict(self)


VALIDATION_CONFIG = ValidationConfig()
XAI_NOTICE = "These results describe model behavior, not causality."
