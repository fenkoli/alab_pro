"""Streamlit interface for the autonomous colour lab.

Run from this directory with:

    uv run --with streamlit --with numpy --with matplotlib streamlit run app.py

Connect, initialise the hardware, measure a target, then use either the model's
suggested recipe or your own.  Pumping and measuring are separate by design:
place/change the cuvette between DONE and Measure.

Check "Simulate hardware" to try the complete workflow without an Arduino.
"""

import matplotlib.pyplot as plt
import streamlit as st

from lab_session import LabSession

st.set_page_config(page_title="Colour Lab", layout="wide")

ACTION_ERRORS = (RuntimeError, TimeoutError, OSError, ValueError)


def recipe_text(recipe):
    return (
        f"red **{recipe[0]} ms**, blue **{recipe[1]} ms**, "
        f"yellow **{recipe[2]} ms**"
    )


def model_figure(lab, view):
    """Prediction, uncertainty and acquisition on the same pump-time grid."""
    step = lab.step_ms
    extent = (-step / 2, lab.total_ms + step / 2,
              -step / 2, lab.total_ms + step / 2)
    panels = (
        ("Predicted score (higher is better)", view["z"], "viridis"),
        ("Model uncertainty", view["z_err"], "magma"),
        (f"Acquisition: score + {lab.beta:g} × uncertainty",
         view["acquisition"], "plasma"),
    )
    history = lab.history()
    measured_x = [entry["ig"] * step for entry in history]
    measured_y = [entry["iq"] * step for entry in history]
    suggestion_i, suggestion_j = view["suggestion_index"]

    fig, axes = plt.subplots(1, 3, figsize=(17, 5), constrained_layout=True)
    for ax, (title, values, cmap) in zip(axes, panels):
        image = ax.imshow(
            values.T,
            origin="lower",
            extent=extent,
            interpolation="nearest",
            aspect="auto",
            cmap=cmap,
        )
        ax.set_title(title)
        ax.set_xlabel("Red pump (ms)")
        ax.set_ylabel("Blue pump (ms)")
        fig.colorbar(image, ax=ax)
        ax.scatter(
            measured_x, measured_y,
            marker="x", s=65, linewidths=3.0, c="black", label="Measured",
        )
        ax.scatter(
            measured_x, measured_y,
            marker="x", s=65, linewidths=1.2, c="white",
        )
        ax.scatter(
            [suggestion_i * step], [suggestion_j * step],
            marker="*", s=260, c="red", edgecolors="white",
            linewidths=1.0, label="Next suggestion",
        )
        ax.legend(loc="upper right", fontsize=8)
    return fig


def main():
    if "lab" not in st.session_state:
        st.session_state.lab = LabSession(simulate=False)
    lab = st.session_state.lab

    st.sidebar.header("Setup")
    simulate = st.sidebar.checkbox(
        "Simulate hardware",
        value=lab.simulate,
        help="Use a smooth fake colour response and no serial connection.",
    )
    if simulate != lab.simulate:
        lab.disconnect()
        lab = LabSession(simulate=simulate)
        st.session_state.lab = lab

    selected_port = None
    ports = [] if lab.simulate else LabSession.available_ports()
    if not lab.simulate:
        labels = [port["label"] for port in ports]
        if labels:
            index = st.sidebar.selectbox(
                "Arduino port",
                range(len(ports)),
                format_func=lambda i: labels[i],
                disabled=lab.connected,
            )
            selected_port = ports[index]["device"]
        else:
            st.sidebar.warning("No serial ports found")

    connect_disabled = lab.connected or (not lab.simulate and selected_port is None)
    if st.sidebar.button("Connect", disabled=connect_disabled):
        try:
            message = lab.connect(selected_port)
            st.session_state.notice = message
            st.rerun()
        except ACTION_ERRORS as exc:
            st.sidebar.error(str(exc))
    if st.sidebar.button("Disconnect", disabled=not lab.connected):
        lab.disconnect()
        st.session_state.notice = "Disconnected"
        st.rerun()

    status = "Connected" if lab.connected else "Not connected"
    st.sidebar.caption(f"{status}: {lab.port or '—'}")

    st.sidebar.header("Initialise")
    st.sidebar.caption("Put the pump lines in the flush container first.")
    if st.sidebar.button("Flush pumps", disabled=not lab.connected):
        try:
            with st.spinner("Flushing pumps..."):
                message = lab.flush()
            st.session_state.notice = message
            st.rerun()
        except ACTION_ERRORS as exc:
            st.sidebar.error(str(exc))

    st.sidebar.caption("Put the white calibration reference in place first.")
    if st.sidebar.button("Calibrate sensor", disabled=not lab.connected):
        try:
            with st.spinner("Calibrating sensor..."):
                message = lab.calibrate()
            st.session_state.notice = message
            st.rerun()
        except ACTION_ERRORS as exc:
            st.sidebar.error(str(exc))

    st.sidebar.header("Target colour")
    samples = st.sidebar.number_input(
        "Reference samples", min_value=2, max_value=20, value=5, step=1
    )
    st.sidebar.caption("Place the reference sample before measuring it.")
    if st.sidebar.button("Measure target", disabled=not lab.connected):
        try:
            with st.spinner(f"Taking {samples} reference readings..."):
                result = lab.measure_reference(samples)
            st.session_state.notice = "Target saved"
            st.sidebar.write(f"Reference RGB: {tuple(result['rgb'])}")
            st.rerun()
        except ACTION_ERRORS as exc:
            st.sidebar.error(str(exc))

    st.title("Autonomous Colour Lab")
    notice = st.session_state.pop("notice", None)
    if notice:
        st.success(notice)

    st.caption(
        f"Data: `{lab.data_csv}` · Grid: {lab.step_ms} ms steps, "
        f"{lab.total_ms} ms total"
    )
    if lab.target_rgb is not None:
        target = [round(value, 1) for value in lab.target_rgb]
        std = lab.target.get("per_channel_std") if lab.target else None
        detail = f" · repeatability {[round(value, 1) for value in std]}" if std else ""
        st.write(f"**Target RGB:** {target}{detail}")
    else:
        st.warning("No target colour. Connect and use Measure target first.")

    if lab.target_rgb is None:
        st.info("The model becomes available after a target colour is measured.")
        return

    try:
        with st.spinner("Updating model..."):
            view = lab.model_view()
    except RuntimeError as exc:
        st.error(str(exc))
        return

    st.pyplot(model_figure(lab, view), width="stretch")
    st.caption(
        "White crosses: measured recipes. Red star: acquisition suggestion. "
        "Blank triangle: invalid (red + blue would exceed total volume)."
    )

    suggested = view["suggestion"]
    st.subheader("Next experiment")
    st.write("Model suggests " + recipe_text(suggested))
    st.caption(
        f"Model's best predicted recipe: {view['predicted_recipe'][:3]} ms "
        f"(score {view['predicted_score']:.1f}). "
        "Score is minus RGB distance, so higher is better."
    )

    busy = not lab.connected or lab.pending_recipe is not None
    if st.button("Pump suggested recipe", disabled=busy):
        try:
            with st.spinner("Pumping suggested recipe..."):
                lab.pump(suggested)
            st.session_state.notice = "Pumping done. Place the cuvette, then Measure."
            st.rerun()
        except ACTION_ERRORS as exc:
            st.error(str(exc))

    st.markdown("**Or choose another recipe**")
    column_red, column_blue, column_yellow = st.columns(3)
    with column_red:
        red = st.number_input(
            "Red pump (ms)", min_value=0, max_value=lab.total_ms,
            value=suggested[0], step=lab.step_ms,
        )
    with column_blue:
        blue = st.number_input(
            "Blue pump (ms)", min_value=0, max_value=lab.total_ms,
            value=suggested[1], step=lab.step_ms,
        )
    with column_yellow:
        yellow = lab.total_ms - red - blue
        st.metric("Yellow derived (ms)", yellow)

    manual_valid = red + blue <= lab.total_ms
    if not manual_valid:
        st.error("Red + blue exceeds total pumping time; reduce a pump time.")
    if st.button("Pump manual recipe", disabled=busy or not manual_valid):
        try:
            with st.spinner("Pumping manual recipe..."):
                lab.pump(LabSession.recipe_from_times(red, blue))
            st.session_state.notice = "Pumping done. Place the cuvette, then Measure."
            st.rerun()
        except ACTION_ERRORS as exc:
            st.error(str(exc))

    if lab.pending_recipe is not None:
        st.info(
            "Pending recipe: " + recipe_text(lab.pending_recipe) +
            ". Place the cuvette now, then measure."
        )
        if st.button("Measure pending sample"):
            try:
                with st.spinner("Reading colour..."):
                    result = lab.measure()
                st.session_state.notice = (
                    f"Measured RGB {tuple(result['rgb'])}; "
                    f"score {result['score']:.1f}"
                )
                st.rerun()
            except ACTION_ERRORS as exc:
                st.error(str(exc))

    if lab.last_result is not None:
        result = lab.last_result
        st.subheader("Last result")
        st.write(
            f"RGB **{result['rgb']}** · score **{result['score']:.1f}** · "
            + recipe_text(result["recipe"])
        )

    st.subheader(f"History ({len(lab.history())} measurements)")
    rows = [
        {
            "Measurement": len(lab.history()) - index,
            "Red (ms)": entry["t"][0],
            "Blue (ms)": entry["t"][1],
            "Yellow (ms)": entry["t"][2],
            "Measured RGB": tuple(entry["rgb"]),
            "Score": round(entry["B"], 1),
        }
        for index, entry in enumerate(reversed(lab.history()))
    ]
    if rows:
        st.dataframe(rows, width="stretch", hide_index=True)
    else:
        st.write("No measured experiments yet.")
    if lab.history_skipped:
        st.caption(
            f"{lab.history_skipped} old CSV row(s) were skipped because they "
            "do not match the 3-pump fixed-total recipe."
        )


main()
