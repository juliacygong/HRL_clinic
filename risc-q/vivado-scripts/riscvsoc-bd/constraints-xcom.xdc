# XCOM constraints that apply however the link is wired (in-fabric loopback or real pins).
#
# xcom_txrx.sv:324-337 puts proper equal-depth 2-FF `synchronizer` chains on the incoming link clock
# and data before the rx block, and xcom_link_rx.sv samples the DELAYED data against the clock edge,
# so one cycle of clk/data skew is tolerated. The RTL is right; what is missing is telling Vivado.
#
# synchronizer.sv sets no ASYNC_REG attribute, so without this the tool is free to retime or
# relocate those two flops and the MTBF the chain exists to provide is not actually delivered.
# Applied in both wiring modes: in loopback the paths are synchronous and this is merely harmless,
# with real pins it is load-bearing.
set_property ASYNC_REG TRUE [get_cells -quiet -hier -regexp {.*sync_xcom_(clk|data)/(meta|sync)_r.*}]
