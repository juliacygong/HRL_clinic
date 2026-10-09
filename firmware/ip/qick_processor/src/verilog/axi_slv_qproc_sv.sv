// axi_slv_qproc_sv.sv

module axi_slv_qproc_sv #(parameter DATA_WIDTH = 32, parameter ADDR_WIDTH = 6)(
    input logic aclk,
    input logic aresetn,

    // Write Address Channel
    input logic [ADDR_WIDTH-1:0] awaddr,
    input logic [2:0] awprot,
    input logic awvalid,
    output logic awready,

    // Write Data Channel
    input logic [DATA_WIDTH-1:0] wdata,
    input logic [(DATA_WIDTH/8)-1:0] wstrb,
    input logic wvalid,
    output logic wready,

    // Write Response Channel
    output logic [1:0] bresp,
    output logic bvalid,
    input logic bready,

    // Read Address Channel
    input logic [ADDR_WIDTH-1:0] araddr,
    input logic [2:0] arprot,
    input logic arvalid,
    output logic arready,

    // Read Data Channel
    output logic [DATA_WIDTH-1:0] rdata,
    output logic [1:0] rresp,
    output logic rvalid,
    input logic rready,

    // Registers
    output logic [15:0] TPROC_CTRL,
    output logic [15:0] TPROC_CFG,
    output logic [15:0] MEM_ADDR,
    output logic [15:0] MEM_LEN,
    output logic [31:0] MEM_DT_I,
    output logic [31:0] TPROC_W_DT1,
    output logic [31:0] TPROC_W_DT2,
    output logic [7:0] CORE_CFG,
    output logic [7:0] READ_SEL,
    input logic [31:0] MEM_DT_O,
    input logic [31:0] TPROC_R_DT1,
    input logic [31:0] TPROC_R_DT2,
    input logic [31:0] TIME_USR,
    input logic [31:0] TPROC_STATUS,
    input logic [31:0] TPROC_DEBUG,

    // Number of Slave Registers 16
    output logic [DATA_WIDTH-1:0] slv_reg0,
    output logic [DATA_WIDTH-1:0] slv_reg1,
    output logic [DATA_WIDTH-1:0] slv_reg2,
    output logic [DATA_WIDTH-1:0] slv_reg3,
    output logic [DATA_WIDTH-1:0] slv_reg4,
    output logic [DATA_WIDTH-1:0] slv_reg5,
    output logic [DATA_WIDTH-1:0] slv_reg6,
    output logic [DATA_WIDTH-1:0] slv_reg7,
    output logic [DATA_WIDTH-1:0] slv_reg8,
    output logic [DATA_WIDTH-1:0] slv_reg9,
    output logic [DATA_WIDTH-1:0] slv_reg10,
    output logic [DATA_WIDTH-1:0] slv_reg11,
    output logic [DATA_WIDTH-1:0] slv_reg12,
    output logic [DATA_WIDTH-1:0] slv_reg13,
    output logic [DATA_WIDTH-1:0] slv_reg14,
    output logic [DATA_WIDTH-1:0] slv_reg15,
    output logic slv_reg_rden,
    output logic slv_reg_wren,
    output logic [DATA_WIDTH-1:0] reg_data_out,
    output logic aw_en
);

    // AXI4LITE signals
    logic [ADDR_WIDTH-1:0] axi_awaddr;
    logic axi_awready;
    logic axi_wready;
    logic [1:0] axi_bresp;
    logic axi_bvalid;
    logic [ADDR_WIDTH-1:0] axi_araddr;
    logic axi_arready;
    logic [DATA_WIDTH-1:0] axi_rdata;
    logic [1:0] axi_rresp;
    logic axi_rvalid;

    localparam int ADDR_LSB = $clog2(DATA_WIDTH/8); //(DATA_WIDTH/32)+1;
    localparam int OPT_MEM_ADDR_BITS = 3;

    // // Number of Slave Registers 16
    // logic [DATA_WIDTH-1:0] slv_reg0;
    // logic [DATA_WIDTH-1:0] slv_reg1;
    // logic [DATA_WIDTH-1:0] slv_reg2;
    // logic [DATA_WIDTH-1:0] slv_reg3;
    // logic [DATA_WIDTH-1:0] slv_reg4;
    // logic [DATA_WIDTH-1:0] slv_reg5;
    // logic [DATA_WIDTH-1:0] slv_reg6;
    // logic [DATA_WIDTH-1:0] slv_reg7;
    // logic [DATA_WIDTH-1:0] slv_reg8;
    // logic [DATA_WIDTH-1:0] slv_reg9;
    // logic [DATA_WIDTH-1:0] slv_reg10;
    // logic [DATA_WIDTH-1:0] slv_reg11;
    // logic [DATA_WIDTH-1:0] slv_reg12;
    // logic [DATA_WIDTH-1:0] slv_reg13;
    // logic [DATA_WIDTH-1:0] slv_reg14;
    // logic [DATA_WIDTH-1:0] slv_reg15;
    // logic slv_reg_rden;
    // logic slv_reg_wren;
    // logic [DATA_WIDTH-1:0] reg_data_out;
    // int byte_index;
    // logic aw_en;

    //I/O Connections assignments
    assign awready = axi_awready;
    assign wready = axi_wready;
    assign bresp = axi_bresp;
    assign bvalid = axi_bvalid;
    assign arready = axi_arready;
    assign rdata = axi_rdata;
    assign rresp = axi_rresp;
    assign rvalid = axi_rvalid;

    always_ff@(posedge aclk) begin 
        if (!aresetn) begin 
            axi_awready <= 0;
            aw_en <= 1;
        end else begin 
            if (axi_awready == 0 && awvalid == 1 && wvalid == 1 && aw_en == 1) begin 
                axi_awready <= 1;
                aw_en <= 0;
            end else if (bready == 1 && axi_bvalid == 1) begin 
                aw_en <= 1;
                axi_awready <= 0;
            end else 
                axi_awready <= 0;
        end 
    end

    // Implement axi_awaddr latching
    always_ff@(posedge aclk) begin 
        if (!aresetn) begin 
            axi_awaddr <= 0;
        end else begin 
            if (axi_awready == 0 && awvalid == 1 && wvalid == 1 && aw_en == 1) begin
                axi_awaddr <= awaddr;
            end
        end
    end

    // Implement axi_wready generation
    always_ff@(posedge aclk) begin 
        if (!aresetn) begin 
            axi_wready <= 0;
        end else begin 
            if (axi_wready == 0 && wvalid == 1 && awvalid == 1 && aw_en == 1) begin 
                axi_wready <= 1;
            end else begin 
                axi_wready <= 0;
            end
        end
        end

    // Implement memory mapped register select and write logic generation
    assign slv_reg_wren = axi_wready && wvalid && axi_awready && awvalid;
    
    wire [OPT_MEM_ADDR_BITS:0] loc_addr_w = axi_awaddr[(ADDR_LSB + OPT_MEM_ADDR_BITS):ADDR_LSB];

    always_ff@(posedge aclk) begin : decoding_regs_aclk
        if (!aresetn) begin 
            slv_reg0 <= 0;
            slv_reg1 <= 0;
            slv_reg2 <= 0;
            slv_reg3 <= 0;
            slv_reg4 <= 0;
            slv_reg5 <= 0;
            slv_reg6 <= 0;
            slv_reg7 <= 0;
            slv_reg8 <= 0;
            slv_reg9 <= 0;
            slv_reg10 <= 0;
            slv_reg11 <= 0;
            slv_reg12 <= 0;
            slv_reg13 <= 0;
            slv_reg14 <= 0;
            slv_reg15 <= 0;
        end else begin 

            if (slv_reg0 != '0) slv_reg0 <= '0;
            if (slv_reg_wren) begin 
                case (loc_addr_w)
                    4'b0000: begin
                           for (int byte_index = 0; byte_index < (DATA_WIDTH/8); byte_index++) begin
                             if (wstrb[byte_index]) begin
                                slv_reg0[(byte_index*8) +: 8] <= wdata[(byte_index*8) +: 8];
                             end
                           end
                         end
                    4'b0001: begin
                        for (int byte_index = 0; byte_index < (DATA_WIDTH/8); byte_index++) begin
                            if (wstrb[byte_index]) begin
                                slv_reg1[(byte_index*8) +: 8] <= wdata[(byte_index*8) +: 8];
                            end
                        end
                    end
                    4'b0010: begin
                        for (int byte_index = 0; byte_index < (DATA_WIDTH/8); byte_index++) begin
                            if (wstrb[byte_index]) begin
                                slv_reg2[(byte_index*8) +: 8] <= wdata[(byte_index*8) +: 8];
                            end
                        end
                    end
                    4'b0011: begin
                        for (int byte_index = 0; byte_index < (DATA_WIDTH/8); byte_index++) begin
                            if (wstrb[byte_index]) begin
                                slv_reg3[(byte_index*8) +: 8] <= wdata[(byte_index*8) +: 8];
                            end
                        end
                    end
                    4'b0100: begin
                        for (int byte_index = 0; byte_index < (DATA_WIDTH/8); byte_index++) begin
                            if (wstrb[byte_index]) begin
                                slv_reg4[(byte_index*8) +: 8] <= wdata[(byte_index*8) +: 8];
                            end
                        end
                    end
                    4'b0101: begin
                        for (int byte_index = 0; byte_index < (DATA_WIDTH/8); byte_index++) begin
                            if (wstrb[byte_index]) begin
                                slv_reg5[(byte_index*8) +: 8] <= wdata[(byte_index*8) +: 8];
                            end
                        end
                    end
                    4'b0110: begin
                        for (int byte_index = 0; byte_index < (DATA_WIDTH/8); byte_index++) begin
                            if (wstrb[byte_index]) begin
                                slv_reg6[(byte_index*8) +: 8] <= wdata[(byte_index*8) +: 8];
                            end
                        end
                    end
                    4'b0111: begin
                        for (int byte_index = 0; byte_index < (DATA_WIDTH/8); byte_index++) begin
                            if (wstrb[byte_index]) begin
                                slv_reg7[(byte_index*8) +: 8] <= wdata[(byte_index*8) +: 8];
                            end
                        end
                    end
                    4'b1000: begin
                        for (int byte_index = 0; byte_index < (DATA_WIDTH/8); byte_index++) begin
                            if (wstrb[byte_index]) begin
                                slv_reg8[(byte_index*8) +: 8] <= wdata[(byte_index*8) +: 8];
                            end
                        end
                    end
                    4'b1001: begin
                        for (int byte_index = 0; byte_index < (DATA_WIDTH/8); byte_index++) begin
                            if (wstrb[byte_index]) begin
                                slv_reg9[(byte_index*8) +: 8] <= wdata[(byte_index*8) +: 8];
                            end
                        end
                    end
                    4'b1010: begin
                        for (int byte_index = 0; byte_index < (DATA_WIDTH/8); byte_index++) begin
                            if (wstrb[byte_index]) begin
                                slv_reg10[(byte_index*8) +: 8] <= wdata[(byte_index*8) +: 8];
                            end
                        end
                    end
                    4'b1011: begin
                        for (int byte_index = 0; byte_index < (DATA_WIDTH/8); byte_index++) begin
                            if (wstrb[byte_index]) begin
                                slv_reg11[(byte_index*8) +: 8] <= wdata[(byte_index*8) +: 8];
                            end
                        end
                    end
                    4'b1100: begin
                        for (int byte_index = 0; byte_index < (DATA_WIDTH/8); byte_index++) begin
                            if (wstrb[byte_index]) begin
                                slv_reg12[(byte_index*8) +: 8] <= wdata[(byte_index*8) +: 8];
                            end
                        end
                    end
                    4'b1101: begin
                        for (int byte_index = 0; byte_index < (DATA_WIDTH/8); byte_index++) begin
                            if (wstrb[byte_index]) begin
                                slv_reg13[(byte_index*8) +: 8] <= wdata[(byte_index*8) +: 8];
                            end
                        end
                    end
                    4'b1110: begin
                        for (int byte_index = 0; byte_index < (DATA_WIDTH/8); byte_index++) begin
                            if (wstrb[byte_index]) begin
                                slv_reg14[(byte_index*8) +: 8] <= wdata[(byte_index*8) +: 8];
                            end
                        end
                    end
                    4'b1111: begin
                        for (int byte_index = 0; byte_index < (DATA_WIDTH/8); byte_index++) begin
                            if (wstrb[byte_index]) begin
                                slv_reg15[(byte_index*8) +: 8] <= wdata[(byte_index*8) +: 8];
                            end
                        end
                    end
                    default: begin
                        // No register write on unspecified addresses; registers hold value.
                    end
                endcase
        end
        end
    end

    // Implement write response logic generation
    always_ff@(posedge aclk) begin 
        if (!aresetn) begin 
            axi_bvalid <= 0;
            axi_bresp <= 0;
        end else begin 
            if (axi_awready == 1 && awvalid == 1 && axi_wready == 1 && wvalid == 1 && axi_bvalid == 0) begin 
                axi_bvalid <= 1;
                axi_bresp <= 0;
            end else if (bready == 1 && axi_bvalid == 1) begin 
                axi_bvalid <= 0;
            end
        end
    end

    // Implement axi_arready generation
    always_ff@(posedge aclk) begin 
        if (!aresetn) begin 
            axi_arready <= 0;
            axi_araddr <= {(ADDR_WIDTH){1'b1}};
        end else begin 
            if (axi_arready == 0 && arvalid == 1) begin 
                axi_arready <= 1;
                axi_araddr <= araddr;
            end else 
                axi_arready <= 0;
        end
    end

    // Implement axi_arvalid generation
    always_ff@(posedge aclk) begin 
        if(!aresetn)  begin
            axi_rvalid <= 0;
            axi_rresp <= 0;
        end else begin 
            if (axi_arready == 1 && arvalid == 1 && axi_rvalid == 0) begin 
                axi_rvalid <= 1;
                axi_rresp <= 0;
            end else if (axi_rvalid == 1 && rready == 1) 
                axi_rvalid <= 0;
        end
    end

    // Implement memory mapped register select and read logic generation
    assign slv_reg_rden = axi_arready && arvalid && (~axi_rvalid);
    
    logic [OPT_MEM_ADDR_BITS:0] loc_addr_r;
        
    assign loc_addr_r = axi_araddr[(ADDR_LSB + OPT_MEM_ADDR_BITS):ADDR_LSB];

    always_comb begin : decoding_regs_no_aclk

        case (loc_addr_r)
            'b0000: reg_data_out = slv_reg0;
            'b0001: reg_data_out = slv_reg1;
            'b0010: reg_data_out = slv_reg2;
            'b0011: reg_data_out = slv_reg3;
            'b0100: reg_data_out = slv_reg4;
            'b0101: reg_data_out = slv_reg5;
            'b0110: reg_data_out = slv_reg6;
            'b0111: reg_data_out = slv_reg7;
            'b1000: reg_data_out = slv_reg8;
            'b1001: reg_data_out = 32'b00000000000000000000000000001001;
            'b1010: reg_data_out = MEM_DT_O;
            'b1011: reg_data_out = TPROC_R_DT1;
            'b1100: reg_data_out = TPROC_R_DT2;
            'b1101: reg_data_out = TIME_USR;
            'b1110: reg_data_out = TPROC_STATUS;
            'b1111: reg_data_out = TPROC_DEBUG;
            default:reg_data_out = 0;
        endcase
    end

    // Output register or memory read data
    always_ff@(posedge aclk) begin 
        if (!aresetn) begin 
            axi_rdata <= 0;
        end else begin 
            if (slv_reg_rden) begin 
                axi_rdata <= reg_data_out;
            end
        end
    end

    // Output registers
    assign TPROC_CTRL = slv_reg0[15:0];
    assign TPROC_CFG = slv_reg1[15:0];
    assign MEM_ADDR = slv_reg2[15:0];
    assign MEM_LEN = slv_reg3[15:0];
    assign MEM_DT_I = slv_reg4[31:0];
    assign TPROC_W_DT1 = slv_reg5[31:0];
    assign TPROC_W_DT2 = slv_reg6[31:0];
    assign CORE_CFG = slv_reg7[7:0];
    assign READ_SEL = slv_reg8[7:0];

endmodule