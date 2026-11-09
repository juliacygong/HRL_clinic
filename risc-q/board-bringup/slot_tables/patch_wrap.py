import runpy, sys
import qick.riscv_toolchain as tc
tc.FLAGS[0] = "-march=rv32im"; tc.FLAGS.append("-Wl,--build-id=none")
sys.argv = ["patch_readout_len.py"] + sys.argv[1:]
runpy.run_path("/home/galencar/HRL_clinic/risc-q/board-bringup/programs/patch_readout_len.py", run_name="__main__")
