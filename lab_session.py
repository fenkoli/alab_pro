"""Shared engine for the colour-lab GUI and simulation tests.

This module connects the v2 Arduino protocol in pro_alab_pyduino_loop_v2.py to
the Bayesian model in ../ml_tests/bo_loop.py.  It deliberately does not use the
old bo_loop.measure(), because that function speaks the older RUN->RGB protocol;
the v2 sketch uses RUN->DONE followed by GO->RGB.

No Streamlit or terminal input here: every action is a method that can be called
by a GUI button or by a test.  Call ALAB_DATA_DIR=<directory> before starting to
store results and target.json somewhere other than ./data.
"""

import os
import sys
import time
from pathlib import Path

import numpy as np

APP_DIR = Path(__file__).resolve().parent
ML_DIR = APP_DIR.parent / "ml_tests"
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import bo_loop
import pro_alab_pyduino_loop_v2 as core

DEFAULT_DATA_DIR = Path(
    os.environ.get("ALAB_DATA_DIR", str(APP_DIR / "data"))
)


class LabSession:
    """One connected lab session.

    Exactly one LabSession should live in st.session_state; creating a new one
    for every Streamlit rerun would reset the Arduino and discard history.
    """

    def __init__(self, simulate=False, sim_seed=0, data_dir=None):
        self.simulate = simulate
        self.sim_seed = sim_seed
        self.data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
        self.data_csv = self.data_dir / "results.csv"
        self.target_json = self.data_dir / "target.json"

        self.connection = None
        self.port = None
        self.connected = False
        self.pending_recipe = None
        self.last_result = None
        self.target = None
        self.history_loaded = 0
        self.history_skipped = 0

        # bo_loop keeps the notebook's configuration in module globals.
        bo_loop.PLOT = False
        bo_loop.DATA_CSV = self.data_csv
        bo_loop.TARGET_JSON = self.target_json
        if simulate:
            bo_loop.init_simulation(sim_seed)
        self.reload_model()

    @staticmethod
    def available_ports():
        """Human-friendly serial-port choices for the GUI."""
        return [
            {"device": port.device, "label": f"{port.device} — {port.description}"}
            for port in core.serial.tools.list_ports.comports()
        ]

    def connect(self, port=None):
        if self.connected:
            return "Already connected"
        if self.simulate:
            self.port = "simulated Arduino"
            self.connected = True
            return "Simulation connected"
        if not port:
            raise ValueError("Choose a serial port first")
        self.connection = core.creating_ard_connection(port)
        self.port = port
        self.connected = True
        return f"Connected to {port}"

    def disconnect(self):
        if self.connection is not None:
            self.connection.close()
        self.connection = None
        self.port = None
        self.connected = False
        self.pending_recipe = None

    def _require_connection(self):
        if not self.connected:
            raise RuntimeError("Connect to the Arduino first")

    def _require_target(self):
        if bo_loop.TARGET_RGB is None:
            raise RuntimeError("Measure or load a target colour first")

    def _wait_for(self, prefix, timeout_s):
        """Wait for an Arduino line, with a timeout instead of hanging."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            line = core.read_line(self.connection)
            if line.startswith(prefix):
                return line
        raise TimeoutError(
            f"Arduino did not send '{prefix}' within {timeout_s:.0f} s. "
            "Check the connection and whether the v2 sketch is running."
        )

    @staticmethod
    def recipe_from_times(t1, t2):
        """Two pump times -> [red, blue, derived yellow, unused] in ms."""
        t1, t2 = int(round(t1)), int(round(t2))
        if t1 < 0 or t2 < 0:
            raise ValueError("Pump times cannot be negative")
        if t1 + t2 > bo_loop.TOTAL_MS:
            raise ValueError(
                f"red + blue must be at most {bo_loop.TOTAL_MS} ms "
                "so that yellow is not negative"
            )
        for value in (t1, t2):
            if value % bo_loop.STEP_MS:
                raise ValueError(
                    f"Use multiples of {bo_loop.STEP_MS} ms for pump times"
                )
        return [t1, t2, bo_loop.TOTAL_MS - t1 - t2, 0]

    def flush(self):
        self._require_connection()
        if self.simulate:
            return "Simulated pump-line flush complete"
        self.connection.reset_input_buffer()
        core.sent_seconds(self.connection, core.FLUSH_MS)
        timeout_s = sum(core.FLUSH_MS) / 1000.0 + 5.0
        self._wait_for("DONE", timeout_s)
        return "Pump-line flush complete"

    def calibrate(self):
        self._require_connection()
        if self.simulate:
            return "Simulated colour-sensor calibration complete"
        self.connection.reset_input_buffer()
        self.connection.write(b"CAL\n")
        self._wait_for("CAL DONE", 10.0)
        return "Colour-sensor calibration complete"

    def measure_reference(self, samples=5):
        """Measure the reference sample and save data/target.json."""
        self._require_connection()
        samples = int(samples)
        if samples < 2:
            raise ValueError("Take at least two reference samples")

        measured = []
        recipe = list(bo_loop.SIM_REFERENCE_RECIPE)
        for _ in range(samples):
            if self.simulate:
                rgb = bo_loop.simulate_rgb(recipe)
            else:
                self.connection.reset_input_buffer()
                self.connection.write(b"GO\n")
                line = self._wait_for("RGB ", 10.0)
                rgb = [int(value) for value in line.split()[1:4]]
            measured.append(rgb)

        array = np.asarray(measured, dtype=float)
        mean = array.mean(axis=0)
        std = array.std(axis=0, ddof=1)
        bo_loop.set_target(mean, std)
        self.target = bo_loop.save_target(mean, std, recipe, samples)
        # Re-score any existing experiments against the new target.
        self.reload_model()
        return {
            "rgb": bo_loop.TARGET_RGB.tolist(),
            "per_channel_std": std.tolist(),
            "samples": measured,
        }

    def reload_model(self):
        """Load target and CSV history into the notebook's data structure."""
        bo_loop.DATA_CSV = self.data_csv
        bo_loop.TARGET_JSON = self.target_json
        bo_loop.reset_data()
        self.target = None
        self.history_loaded = self.history_skipped = 0
        if self.target_json.exists():
            self.target = bo_loop.load_target(self.target_json)
            self.history_loaded, self.history_skipped = bo_loop.load_history(
                self.data_csv, verbose=False
            )

    def model_view(self):
        """Return prediction, uncertainty and acquisition arrays for plotting."""
        self._require_target()
        z, z_err = bo_loop.train_and_evaluate(
            bo_loop.data,
            bo_loop.BV0,
            bo_loop.DELTA_BV,
            bo_loop.SIGMA_BV,
            bo_loop.DELTA_IJ,
            plot=False,
        )
        invalid = bo_loop.invalid_mask()
        valid = ~invalid
        acquisition = z + bo_loop.BETA * z_err

        i, j = bo_loop.argmaxN(np.where(invalid, -np.inf, acquisition), 2)
        best_z = np.where(invalid, -np.inf, z)
        best_i, best_j = bo_loop.argmaxN(best_z, 2)

        # NaN cells are blank in matplotlib; -inf is only for argmax above.
        return {
            "z": np.where(valid, z, np.nan),
            "z_err": np.where(valid, z_err, np.nan),
            "acquisition": np.where(valid, acquisition, np.nan),
            "suggestion": bo_loop.grid_pump_ms(i, j),
            "suggestion_index": (int(i), int(j)),
            "predicted_recipe": bo_loop.grid_pump_ms(best_i, best_j),
            "predicted_score": float(best_z[best_i, best_j]),
        }

    def pump(self, recipe):
        """Pump one recipe and wait for DONE; measurement is a separate action."""
        self._require_connection()
        self._require_target()
        if self.pending_recipe is not None:
            raise RuntimeError(
                "Measure the current pending recipe before pumping another one"
            )
        if len(recipe) != 4:
            raise ValueError("A recipe needs four pump times")
        t1, t2, t3, t4 = [int(round(value)) for value in recipe]
        recipe = self.recipe_from_times(t1, t2)
        if t3 != recipe[2] or t4 != 0:
            raise ValueError(
                "Yellow must be total - red - blue and the fourth pump must be 0"
            )

        self.pending_recipe = recipe
        if self.simulate:
            return recipe

        self.connection.reset_input_buffer()
        core.sent_seconds(self.connection, recipe)
        timeout_s = sum(recipe) / 1000.0 + 5.0
        self._wait_for("DONE", timeout_s)
        return recipe

    def measure(self):
        """Read the pumped sample, save CSV, and add it to the ML model."""
        self._require_connection()
        self._require_target()
        if self.pending_recipe is None:
            raise RuntimeError("Pump a recipe before measuring")

        recipe = self.pending_recipe
        if self.simulate:
            rgb = bo_loop.simulate_rgb(recipe)
        else:
            self.connection.reset_input_buffer()
            self.connection.write(b"GO\n")
            line = self._wait_for("RGB ", 10.0)
            rgb = [int(value) for value in line.split()[1:4]]

        score = bo_loop.score(rgb)
        bo_loop.save_result(recipe, rgb)
        bo_loop.add_measurement(recipe, rgb)
        self.history_loaded += 1
        self.pending_recipe = None
        self.last_result = {
            "recipe": recipe,
            "rgb": rgb,
            "score": score,
            "measurement_number": len(bo_loop.data),
        }
        return self.last_result

    def history(self):
        """Measurement dictionaries from bo_loop, oldest first."""
        return list(bo_loop.data)

    @property
    def target_rgb(self):
        return None if bo_loop.TARGET_RGB is None else bo_loop.TARGET_RGB.tolist()

    @property
    def total_ms(self):
        return bo_loop.TOTAL_MS

    @property
    def step_ms(self):
        return bo_loop.STEP_MS

    @property
    def beta(self):
        return bo_loop.BETA
