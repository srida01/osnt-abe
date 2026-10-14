from nest import config
from nest.experiment import Experiment
from nest.topology.topology_helpers.dumbbell import DumbbellHelper

# Keep namespaces after NeST exits
config.set_value("assign_random_names", False)
config.set_value("delete_namespaces_on_termination", False)

# --------------------------------------------------
# 1. Create dumbbell topology
# --------------------------------------------------
#
# 2 senders
# 2 receivers
# 2 routers
#
#        S1 ───── R1 ===== R2 ───── D1
#        S2 ───── R1 ===== R2 ───── D2
#                    bottleneck
#
topology = DumbbellHelper(
    {
        "left": 2,
        "right": 2,
        "routers": 2,
    },
    use_ipv6=False,
    use_dynamic_routing=False,
)

# --------------------------------------------------
# 2. Configure edge links
# --------------------------------------------------

for i in range(2):
    topology.get_left_interface(i).set_attributes(
        "100mbit", "1ms", "pfifo"
    )

    topology.get_right_interface(i).set_attributes(
        "100mbit", "1ms", "pfifo"
    )

# --------------------------------------------------
# 3. Configure bottleneck
# --------------------------------------------------

r1_r2 = topology.get_router_interface(0, -1)
r2_r1 = topology.get_router_interface(1, 0)

r1_r2.set_attributes("10mbit", "20ms", "pfifo")
r2_r1.set_attributes("10mbit", "20ms", "pfifo")

# --------------------------------------------------
# 4. Experiment
# --------------------------------------------------

exp = Experiment("msquic-cubic-baseline")

# Collect bottleneck qdisc statistics
exp.require_qdisc_stats(r1_r2)

exp.run()
