"""
Z-Y Scan Monitor  —  DEMO MODE TEST
Requirements: pip install matplotlib
"""

import time, math, random, threading, datetime
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
import matplotlib.animation as animation
from matplotlib.widgets import CheckButtons

# ══════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════
SOURCE_V        = 2.0
Y_TOTAL         = 20
Z_TOTAL         = 110
Z_STEP_UM       = 10.0
Y_STEP_UM       = 25.0
SAMPLE_INTERVAL = 0.05
STOP_UA         = 1.0
DARK_A          = 200e-12

COLORS = ["#89dceb","#cba6f7","#f38ba8","#fab387","#a6e3a1",
          "#89b4fa","#f9e2af","#94e2d5","#eba0ac","#b4befe"]

# ══════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════
def gauss(x, mu, sig, amp):
    return amp * math.exp(-0.5*((x-mu)/sig)**2)

def sim_current(y_idx, z_idx):
    z = z_idx*Z_STEP_UM; y = y_idx*Y_STEP_UM
    zn = z/(Z_TOTAL*Z_STEP_UM); yn = y/(Y_TOTAL*Y_STEP_UM)
    i  = DARK_A
    i += gauss(zn,0.12,0.02,180e-12)
    i += gauss(zn,0.28,0.03,320e-12)
    i += gauss(zn,0.43,0.015,150e-12)
    i += gauss(zn,0.58,0.015,420e-12)
    yf = gauss(yn,0.25,0.18,1.0)
    i += gauss(zn,0.62,0.004,1.35e-6*yf)
    i += random.gauss(0,8e-12)
    return max(0.0, i)

def auto_unit(val_a):
    a = abs(val_a)
    if a>=1e-3: return 1e3,"mA"
    if a>=1e-6: return 1e6,"µA"
    if a>=1e-9: return 1e9,"nA"
    return 1e12,"pA"

def fmt_time(s):
    s = max(0,int(s)); h,m,sec = s//3600,(s%3600)//60,s%60
    return f"{h:02d}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"

# ══════════════════════════════════════════════
# State
# ══════════════════════════════════════════════
class ScanState:
    def __init__(self):
        self.lock         = threading.Lock()
        self.started_at   = None
        self.elapsed_s    = 0.0
        self.remaining_s  = 0.0
        self.y_idx        = 0
        self.z_idx        = 0
        self.y_um         = 0.0
        self.z_um         = 0.0
        self.current_a    = DARK_A
        self.compliance   = False
        self.stopped      = False
        self.done         = False
        self.restart      = False
        self.loop_enabled = False
        self.z_line       = []
        self.i_line       = []
        self.prev_lines   = []

def reset_state(s):
    s.started_at=datetime.datetime.now(); s.elapsed_s=0.0; s.remaining_s=0.0
    s.y_idx=0; s.z_idx=0; s.y_um=0.0; s.z_um=0.0; s.current_a=DARK_A
    s.compliance=False; s.stopped=False; s.done=False; s.restart=False
    s.z_line=[]; s.i_line=[]; s.prev_lines=[]

# ══════════════════════════════════════════════
# Sim thread
# ══════════════════════════════════════════════
def sim_thread_fn(state):
    while True:
        with state.lock: reset_state(state)
        total=Y_TOTAL*Z_TOTAL; cnt=0; t0=time.time()
        for yi in range(Y_TOTAL):
            zr = range(Z_TOTAL) if yi%2==0 else range(Z_TOTAL-1,-1,-1)
            with state.lock:
                state.prev_lines.append((list(state.z_line),list(state.i_line),state.y_idx))
                state.z_line=[]; state.i_line=[]; state.y_idx=yi; state.y_um=yi*Y_STEP_UM
            for zi in zr:
                with state.lock:
                    if state.restart: break
                i_a=sim_current(yi,zi); z_um=zi*Z_STEP_UM
                el=time.time()-t0; cnt+=1
                rem=(el/cnt)*(total-cnt) if cnt else 0
                with state.lock:
                    state.z_idx=zi; state.z_um=z_um; state.current_a=i_a
                    state.elapsed_s=el; state.remaining_s=rem
                    state.z_line.append(z_um); state.i_line.append(i_a)
                    if i_a*1e6>=STOP_UA: state.stopped=True
                if state.stopped: break
                time.sleep(SAMPLE_INTERVAL)
            with state.lock: nb=state.stopped or state.restart
            if nb: break
        with state.lock: state.done=True
        while True:
            time.sleep(0.1)
            with state.lock:
                if state.restart: break

# ══════════════════════════════════════════════
# Plot
# ══════════════════════════════════════════════
def run_plot(state):
    # figure margin (figure fraction)
    L,R,T,B = 0.07, 0.97, 0.97, 0.07

    fig = plt.figure(figsize=(14,8), facecolor="#1e1e2e")
    fig.canvas.manager.set_window_title("Scan Monitor  —  DEMO MODE")

    gs = gridspec.GridSpec(3,1, height_ratios=[1.2,0.9,2.5],
                           hspace=0.0,
                           left=L, right=R, top=T, bottom=B)

    # ── Panel 1: Meter ───────────────────────────────────
    ax_m = fig.add_subplot(gs[0])
    ax_m.set_facecolor("#0a0a14")
    ax_m.set_xticks([]); ax_m.set_yticks([])
    for sp in ax_m.spines.values(): sp.set_edgecolor("#313244")

    ax_m.text(0.01,0.97,"CURRENT",transform=ax_m.transAxes,
              color="#00cc7a",fontsize=10,fontweight="bold",va="top",fontfamily="monospace")
    ax_m.text(0.01,0.15,f"Vsrc = {SOURCE_V} V",transform=ax_m.transAxes,
              color="#585b70",fontsize=8,va="top",fontfamily="monospace")
    ax_m.text(0.35,0.97,"DEMO MODE",transform=ax_m.transAxes,
              color="#f38ba8",fontsize=9,fontweight="bold",va="top",ha="center",fontfamily="monospace")

    disp_val  = ax_m.text(0.30,0.52,"000.0000",transform=ax_m.transAxes,
                          color="#00ff9f",fontsize=44,fontweight="bold",
                          ha="center",va="center",fontfamily="monospace")
    disp_unit = ax_m.text(0.56,0.52,"pA",transform=ax_m.transAxes,
                          color="#00cc7a",fontsize=20,fontweight="bold",
                          ha="center",va="center",fontfamily="monospace")
    disp_stat = ax_m.text(0.30,0.10,"■ NORMAL",transform=ax_m.transAxes,
                          color="#a6e3a1",fontsize=9,ha="center",va="bottom",fontfamily="monospace")

    ax_m.axvline(x=0.68,color="#313244",lw=0.8)
    ax_m.text(0.77,0.97,"Y POSITION",transform=ax_m.transAxes,
              color="#cba6f7",fontsize=10,fontweight="bold",va="top",ha="center",fontfamily="monospace")
    ax_m.text(0.92,0.97,"Z POSITION",transform=ax_m.transAxes,
              color="#89b4fa",fontsize=10,fontweight="bold",va="top",ha="center",fontfamily="monospace")
    disp_y = ax_m.text(0.77,0.55,"0.0",transform=ax_m.transAxes,
                       color="#cba6f7",fontsize=28,fontweight="bold",
                       ha="center",va="center",fontfamily="monospace")
    disp_z = ax_m.text(0.92,0.55,"0.0",transform=ax_m.transAxes,
                       color="#89b4fa",fontsize=28,fontweight="bold",
                       ha="center",va="center",fontfamily="monospace")
    ax_m.text(0.77,0.16,"µm",transform=ax_m.transAxes,
              color="#cba6f7",fontsize=9,ha="center",va="top",fontfamily="monospace")
    ax_m.text(0.92,0.16,"µm",transform=ax_m.transAxes,
              color="#89b4fa",fontsize=9,ha="center",va="top",fontfamily="monospace")

    # ── Panel 2: Progress ────────────────────────────────
    ax_p = fig.add_subplot(gs[1])
    ax_p.set_facecolor("#11111e")
    ax_p.set_xticks([]); ax_p.set_yticks([])
    ax_p.set_xlim(0,1); ax_p.set_ylim(0,1)
    for sp in ax_p.spines.values(): sp.set_edgecolor("#313244")

    txt_start   = ax_p.text(0.01,0.88,"Started  : --:--:--",
                             color="#cdd6f4",fontsize=9,va="top",fontfamily="monospace")
    txt_elapsed = ax_p.text(0.01,0.58,"Elapsed  : 00:00",
                             color="#cdd6f4",fontsize=9,va="top",fontfamily="monospace")
    txt_remain  = ax_p.text(0.01,0.28,"Remaining: --:--",
                             color="#cdd6f4",fontsize=9,va="top",fontfamily="monospace")

    # progress bar — ใช้ ax_p.transAxes เหมือนกันหมด ไม่มี add_axes
    BX,BY,BW,BH = 0.22, 0.48, 0.52, 0.26
    ax_p.add_patch(mpatches.FancyBboxPatch(
        (BX,BY),BW,BH, boxstyle="round,pad=0.01",
        facecolor="#313244",edgecolor="#45475a",linewidth=0.5,
        transform=ax_p.transAxes))
    prog_fill = ax_p.add_patch(mpatches.FancyBboxPatch(
        (BX,BY),0.001,BH, boxstyle="round,pad=0.01",
        facecolor="#1D9E75",edgecolor="none",
        transform=ax_p.transAxes))
    txt_pct = ax_p.text(BX+BW/2,BY+BH/2,"0%",
                         transform=ax_p.transAxes,
                         color="#cdd6f4",fontsize=10,fontweight="bold",
                         ha="center",va="center",fontfamily="monospace")
    txt_yz  = ax_p.text(BX,BY-0.10,"",
                         transform=ax_p.transAxes,
                         color="#9399b2",fontsize=8,va="top",fontfamily="monospace")

    # RESTART button — วาดใน ax_p.transAxes เลย ไม่ใช้ add_axes
    RBX,RBY,RBW,RBH = 0.76, 0.52, 0.22, 0.30
    btn_patch = ax_p.add_patch(mpatches.FancyBboxPatch(
        (RBX,RBY),RBW,RBH, boxstyle="round,pad=0.01",
        facecolor="#313244",edgecolor="#585b70",linewidth=1.0,
        transform=ax_p.transAxes, zorder=3, picker=True))
    btn_txt = ax_p.text(RBX+RBW/2,RBY+RBH/2,"↺  RESTART",
                         transform=ax_p.transAxes,
                         color="#cdd6f4",fontsize=10,fontweight="bold",
                         ha="center",va="center",fontfamily="monospace",zorder=4)

    # Auto Loop checkbox — วาดใน ax_p.transAxes เช่นกัน
    CBX,CBY,CBW,CBH = 0.76, 0.10, 0.22, 0.32
    chk_border = ax_p.add_patch(mpatches.FancyBboxPatch(
        (CBX,CBY),CBW,CBH, boxstyle="round,pad=0.01",
        facecolor="#11111e",edgecolor="#fab387",linewidth=1.0,
        transform=ax_p.transAxes, zorder=3))
    # checkbox box
    BOX=0.025
    chk_box = ax_p.add_patch(mpatches.FancyBboxPatch(
        (CBX+0.03, CBY+CBH/2-BOX), BOX*2,BOX*2,
        boxstyle="round,pad=0.002",
        facecolor="#11111e",edgecolor="#fab387",linewidth=1.0,
        transform=ax_p.transAxes, zorder=4))
    chk_mark = ax_p.text(CBX+0.03+BOX, CBY+CBH/2,"",
                          transform=ax_p.transAxes,
                          color="#fab387",fontsize=10,fontweight="bold",
                          ha="center",va="center",zorder=5)
    ax_p.text(CBX+0.09, CBY+CBH/2,"Auto Loop",
              transform=ax_p.transAxes,
              color="#fab387",fontsize=9,fontweight="bold",
              ha="left",va="center",fontfamily="monospace",zorder=4)

    loop_state = [False]  # mutable container

    def on_click(ev):
        if ev.inaxes == ax_p:
            # ตรวจว่าคลิกใน RESTART box
            if RBX<=ev.xdata<=RBX+RBW and RBY<=ev.ydata<=RBY+RBH:
                with state.lock: state.restart=True
                btn_patch.set_facecolor("#45475a")
                fig.canvas.draw_idle()
            # ตรวจว่าคลิกใน Auto Loop box
            elif CBX<=ev.xdata<=CBX+CBW and CBY<=ev.ydata<=CBY+CBH:
                loop_state[0] = not loop_state[0]
                with state.lock: state.loop_enabled=loop_state[0]
                chk_box.set_facecolor("#fab387" if loop_state[0] else "#11111e")
                chk_mark.set_text("✓" if loop_state[0] else "")
                fig.canvas.draw_idle()

    def on_release(ev):
        btn_patch.set_facecolor("#313244")
        fig.canvas.draw_idle()

    fig.canvas.mpl_connect("button_press_event",   on_click)
    fig.canvas.mpl_connect("button_release_event", on_release)

    # ── Panel 3: Graph ───────────────────────────────────
    ax_g = fig.add_subplot(gs[2])
    ax_g.set_facecolor("#1e1e2e")
    ax_g.set_xlabel("Z position (µm)",color="#cdd6f4",fontsize=11)
    ax_g.set_ylabel("Current I",      color="#cdd6f4",fontsize=11)
    ax_g.tick_params(colors="#cdd6f4")
    for sp in ax_g.spines.values(): sp.set_edgecolor("#45475a")
    ax_g.set_xlim(0,Z_TOTAL*Z_STEP_UM)
    ax_g.axhline(y=STOP_UA,color="#f38ba8",lw=1.0,ls="--",alpha=0.7)
    ax_g.text(Z_TOTAL*Z_STEP_UM*0.98,STOP_UA*1.05,"stop 1 µA",
              color="#f38ba8",fontsize=8,ha="right")

    cur_line,  = ax_g.plot([],[],lw=1.8,color=COLORS[0],zorder=5)
    prev_arts  = []
    g_title    = ax_g.text(0.01,0.97,"",transform=ax_g.transAxes,
                            color="#9399b2",fontsize=9,va="top",fontfamily="monospace")

    # ── Animate ──────────────────────────────────────────
    def update(_):
        with state.lock:
            started=state.started_at; elapsed=state.elapsed_s
            remaining=state.remaining_s; yi=state.y_idx; zi=state.z_idx
            y_um=state.y_um; z_um=state.z_um; i_a=state.current_a
            comp=state.compliance; stopped=state.stopped; done=state.done
            zl=list(state.z_line); il=list(state.i_line); prev=list(state.prev_lines)

        if done:
            with state.lock:
                if state.loop_enabled: state.restart=True

        # meter
        disp_y.set_text(f"{y_um:.1f}"); disp_z.set_text(f"{z_um:.1f}")
        sc,unit = auto_unit(i_a)
        disp_val.set_text(f"{i_a*sc:>10.4f}"); disp_unit.set_text(unit)
        if comp or stopped:
            disp_val.set_color("#ff5555")
            disp_stat.set_text("■ COMPLIANCE!" if comp else "■ STOPPED")
            disp_stat.set_color("#f38ba8")
        elif done:
            disp_val.set_color("#89b4fa"); disp_stat.set_text("■ DONE"); disp_stat.set_color("#89b4fa")
        else:
            disp_val.set_color("#00ff9f"); disp_stat.set_text("■ SCANNING"); disp_stat.set_color("#a6e3a1")

        # time
        if started: txt_start.set_text(f"Started  : {started.strftime('%H:%M:%S')}")
        txt_elapsed.set_text(f"Elapsed  : {fmt_time(elapsed)}")
        txt_remain.set_text( f"Remaining: {fmt_time(remaining)}")

        # progress
        pct = (yi*Z_TOTAL+zi)/(Y_TOTAL*Z_TOTAL) if Y_TOTAL*Z_TOTAL else 0
        prog_fill.set_width(max(0.001,BW*pct))
        txt_pct.set_text(f"{pct*100:.1f}%")
        txt_yz.set_text(f"Y line: {yi+1}/{Y_TOTAL}   Z step: {zi+1}/{Z_TOTAL}   "
                        f"Y={y_um:.0f}µm  Z={z_um:.0f}µm")
        if pct>0.5:  prog_fill.set_facecolor("#1D9E75")
        if pct>0.8:  prog_fill.set_facecolor("#89b4fa")

        # graph
        for a in prev_arts: a.remove()
        prev_arts.clear()
        sc_g,unit_g = auto_unit(max([max(il)] if il else [i_a], default=DARK_A))
        for pz,pi,pyi in prev[-8:]:
            if not pz: continue
            art, = ax_g.plot(pz,[v*sc_g for v in pi],lw=0.8,
                             color=COLORS[pyi%len(COLORS)],alpha=0.25,zorder=2)
            prev_arts.append(art)
        if zl:
            il_sc=[v*sc_g for v in il]
            cur_line.set_data(zl,il_sc); cur_line.set_color(COLORS[yi%len(COLORS)])
            ymax=max([max(il_sc)]+[max([v*sc_g for v in pi],default=0)
                     for _,pi,_ in prev[-8:] if pi])
            ax_g.set_ylim(-ymax*0.05,ymax*1.3)
            ax_g.set_ylabel(f"Current I ({unit_g})",color="#cdd6f4",fontsize=11)
            ax_g.axhline(y=STOP_UA,color="#f38ba8",lw=1.0,ls="--",alpha=0.7)
        g_title.set_text(f"Y line {yi+1}/{Y_TOTAL}  (Y={y_um:.0f}µm)  —  "
                         f"{'STOPPED' if stopped else 'DONE' if done else 'scanning...'}")
        fig.canvas.draw_idle()

    ani = animation.FuncAnimation(fig,update,interval=150,cache_frame_data=False)
    plt.show()

# ══════════════════════════════════════════════
if __name__ == "__main__":
    print("="*50)
    print("  DEMO MODE — ไม่ต้องต่ออุปกรณ์จริง")
    print(f"  Y: {Y_TOTAL} lines   Z: {Z_TOTAL} steps   Stop: {STOP_UA} µA")
    print("="*50)
    state = ScanState()
    t = threading.Thread(target=sim_thread_fn,args=(state,),daemon=True)
    t.start()
    run_plot(state)
    t.join()
    print("\n[Done]")
