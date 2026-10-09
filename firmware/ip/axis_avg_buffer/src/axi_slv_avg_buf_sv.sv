module axi_slv_avg_buf_sv #(
    parameter int DATA_WIDTH = 32,
    parameter int ADDR_WIDTH = 6
)(
    input  logic                         aclk,
    input  logic                         aresetn,

    // Write Address Channel
    input  logic [ADDR_WIDTH-1:0]        awaddr,
    input  logic [2:0]                   awprot,
    input  logic                         awvalid,
    output logic                         awready,

    // Write Data Channel
    input  logic [DATA_WIDTH-1:0]        wdata,
    input  logic [(DATA_WIDTH/8)-1:0]    wstrb,
    input  logic                         wvalid,
    output logic                         wready,

    // Write Response Channel
    output logic [1:0]                   bresp,
    output logic                         bvalid,
    input  logic                         bready,

    // Read Address Channel
    input  logic [ADDR_WIDTH-1:0]        araddr,
    input  logic [2:0]                   arprot,
    input  logic                         arvalid,
    output logic                         arready,

    // Read Data Channel
    output logic [DATA_WIDTH-1:0]        rdata,
    output logic [1:0]                   rresp,
    output logic                         rvalid,
    input  logic                         rready,

    // User Registers
    output logic                         AVG_START_REG,
    output logic [31:0]                  AVG_ADDR_REG,
    output logic [31:0]                  AVG_LEN_REG,
    output logic                         AVG_PHOTON_MODE_REG,
    output logic [31:0]                  AVG_H_THRSH_REG,
    output logic [31:0]                  AVG_L_THRSH_REG,
    output logic                         AVG_DR_START_REG,
    output logic [31:0]                  AVG_DR_ADDR_REG,
    output logic [31:0]                  AVG_DR_LEN_REG,
    output logic                         BUF_START_REG,
    output logic [31:0]                  BUF_ADDR_REG,
    output logic [31:0]                  BUF_LEN_REG,
    output logic                         BUF_DR_START_REG,
    output logic [31:0]                  BUF_DR_ADDR_REG,
    output logic [31:0]                  BUF_DR_LEN_REG
);

    // Local parameters
    localparam int ADDR_LSB = (DATA_WIDTH/32) + 1;   // =2 for 32-bit
    localparam int OPT_MEM_ADDR_BITS = 3;             // 16 regs

    // Internal AXI signals
    logic [ADDR_WIDTH-1:0] axi_awaddr;
    logic                  axi_awready;
    logic                  axi_wready;
    logic [1:0]            axi_bresp;
    logic                  axi_bvalid;
    logic [ADDR_WIDTH-1:0] axi_araddr;
    logic                  axi_arready;
    logic [DATA_WIDTH-1:0] axi_rdata;
    logic [1:0]            axi_rresp;
    logic                  axi_rvalid;

    logic                  aw_en;

    assign awready = axi_awready;
    assign wready  = axi_wready;
    assign bresp   = axi_bresp;
    assign bvalid  = axi_bvalid;
    assign arready = axi_arready;
    assign rdata   = axi_rdata;
    assign rresp   = axi_rresp;
    assign rvalid  = axi_rvalid;

    // Number of Slave Registers 16
    logic [DATA_WIDTH-1:0] slv_reg0;
    logic [DATA_WIDTH-1:0] slv_reg1;
    logic [DATA_WIDTH-1:0] slv_reg2;
    logic [DATA_WIDTH-1:0] slv_reg3;
    logic [DATA_WIDTH-1:0] slv_reg4;
    logic [DATA_WIDTH-1:0] slv_reg5;
    logic [DATA_WIDTH-1:0] slv_reg6;
    logic [DATA_WIDTH-1:0] slv_reg7;
    logic [DATA_WIDTH-1:0] slv_reg8;
    logic [DATA_WIDTH-1:0] slv_reg9;
    logic [DATA_WIDTH-1:0] slv_reg10;
    logic [DATA_WIDTH-1:0] slv_reg11;
    logic [DATA_WIDTH-1:0] slv_reg12;
    logic [DATA_WIDTH-1:0] slv_reg13;
    logic [DATA_WIDTH-1:0] slv_reg14;
    logic [DATA_WIDTH-1:0] slv_reg15;

    // Slave registers (16 x DATA_WIDTH)
    logic [DATA_WIDTH-1:0] slv_reg [0:15];
    logic                  slv_reg_wren;
    logic                  slv_reg_rden;
    logic [DATA_WIDTH-1:0] reg_data_out;

    // Write Address Ready
    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            axi_awready <= 1'b0;
            aw_en       <= 1'b1;
        end else begin
            if (!axi_awready && awvalid && wvalid && aw_en) begin
                axi_awready <= 1'b1;
                aw_en       <= 1'b0;
            end else if (bready && axi_bvalid) begin
                aw_en       <= 1'b1;
                axi_awready <= 1'b0;
            end else begin
                axi_awready <= 1'b0;
            end
        end
    end

    // Latch write address
    always_ff @(posedge aclk) begin
        if (!aresetn)
            axi_awaddr <= '0;
        else if (!axi_awready && awvalid && wvalid && aw_en)
            axi_awaddr <= awaddr;
    end

    // Write Data Ready
    always_ff @(posedge aclk) begin
        if (!aresetn)
            axi_wready <= 1'b0;
        else if (!axi_wready && wvalid && awvalid && aw_en)
            axi_wready <= 1'b1;
        else
            axi_wready <= 1'b0;
    end

    assign slv_reg_wren = axi_wready && wvalid && axi_awready && awvalid;

    // Register Write Logic
    logic [OPT_MEM_ADDR_BITS:0] loc_addr;
    assign loc_addr = axi_awaddr[(ADDR_LSB + OPT_MEM_ADDR_BITS):ADDR_LSB];
    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            slv_reg0  <= '0;
            slv_reg1  <= '0;
            slv_reg2  <= '0;
            slv_reg3  <= '0;
            slv_reg4  <= '0;
            slv_reg5  <= '0;
            slv_reg6  <= '0;
            slv_reg7  <= '0;
            slv_reg8  <= '0;
            slv_reg9  <= '0;
            slv_reg10 <= '0;
            slv_reg11 <= '0;
            slv_reg12 <= '0;
            slv_reg13 <= '0;
            slv_reg14 <= '0;
            slv_reg15 <= '0;
        end 
        else if (slv_reg_wren) begin
            if (slv_reg_wren) begin
                case (loc_addr)
                    4'b0000: begin
                           for (int byte_index = 0; byte_index < (DATA_WIDTH/8); byte_index++) begin
                             if (wstrb[byte_index]) begin
                             slv_reg0[(byte_index*8) +: 8] <= wdata[(byte_index*8) +: 8];
                             end
                           end
                         end
                    4'b0001: begin
                        int byte_index; // procedural loop variable
                        for (byte_index = 0; byte_index < (DATA_WIDTH/8); byte_index++) begin
                            if (wstrb[byte_index]) begin
                                slv_reg1[(byte_index*8) +: 8] <= wdata[(byte_index*8) +: 8];
                            end
                        end
                    end
                    4'b0010: begin
                        int byte_index; // procedural loop variable
                        for (byte_index = 0; byte_index < (DATA_WIDTH/8); byte_index++) begin
                            if (wstrb[byte_index]) begin
                                slv_reg2[(byte_index*8) +: 8] <= wdata[(byte_index*8) +: 8];
                            end
                        end
                    end
                    4'b0011: begin
                        int byte_index; // procedural loop variable
                        for (byte_index = 0; byte_index < (DATA_WIDTH/8); byte_index++) begin
                            if (wstrb[byte_index]) begin
                                slv_reg3[(byte_index*8) +: 8] <= wdata[(byte_index*8) +: 8];
                            end
                        end
                    end
                    4'b0100: begin
                        int byte_index; // procedural loop variable
                        for (byte_index = 0; byte_index < (DATA_WIDTH/8); byte_index++) begin
                            if (wstrb[byte_index]) begin
                                slv_reg4[(byte_index*8) +: 8] <= wdata[(byte_index*8) +: 8];
                            end
                        end
                    end
                    4'b0101: begin
                        int byte_index; // procedural loop variable
                        for (byte_index = 0; byte_index < (DATA_WIDTH/8); byte_index++) begin
                            if (wstrb[byte_index]) begin
                                slv_reg5[(byte_index*8) +: 8] <= wdata[(byte_index*8) +: 8];
                            end
                        end
                    end
                    4'b0110: begin
                        int byte_index; // procedural loop variable
                        for (byte_index = 0; byte_index < (DATA_WIDTH/8); byte_index++) begin
                            if (wstrb[byte_index]) begin
                                slv_reg6[(byte_index*8) +: 8] <= wdata[(byte_index*8) +: 8];
                            end
                        end
                    end
                    4'b0111: begin
                        int byte_index; // procedural loop variable
                        for (byte_index = 0; byte_index < (DATA_WIDTH/8); byte_index++) begin
                            if (wstrb[byte_index]) begin
                                slv_reg7[(byte_index*8) +: 8] <= wdata[(byte_index*8) +: 8];
                            end
                        end
                    end
                    4'b1000: begin
                        int byte_index; // procedural loop variable
                        for (byte_index = 0; byte_index < (DATA_WIDTH/8); byte_index++) begin
                            if (wstrb[byte_index]) begin
                                slv_reg8[(byte_index*8) +: 8] <= wdata[(byte_index*8) +: 8];
                            end
                        end
                    end
                    4'b1001: begin
                        int byte_index; // procedural loop variable
                        for (byte_index = 0; byte_index < (DATA_WIDTH/8); byte_index++) begin
                            if (wstrb[byte_index]) begin
                                slv_reg9[(byte_index*8) +: 8] <= wdata[(byte_index*8) +: 8];
                            end
                        end
                    end
                    4'b1010: begin
                        int byte_index; // procedural loop variable
                        for (byte_index = 0; byte_index < (DATA_WIDTH/8); byte_index++) begin
                            if (wstrb[byte_index]) begin
                                slv_reg10[(byte_index*8) +: 8] <= wdata[(byte_index*8) +: 8];
                            end
                        end
                    end
                    4'b1011: begin
                        int byte_index; // procedural loop variable
                        for (byte_index = 0; byte_index < (DATA_WIDTH/8); byte_index++) begin
                            if (wstrb[byte_index]) begin
                                slv_reg11[(byte_index*8) +: 8] <= wdata[(byte_index*8) +: 8];
                            end
                        end
                    end
                    4'b1100: begin
                        int byte_index; // procedural loop variable
                        for (byte_index = 0; byte_index < (DATA_WIDTH/8); byte_index++) begin
                            if (wstrb[byte_index]) begin
                                slv_reg12[(byte_index*8) +: 8] <= wdata[(byte_index*8) +: 8];
                            end
                        end
                    end
                    4'b1101: begin
                        int byte_index; // procedural loop variable
                        for (byte_index = 0; byte_index < (DATA_WIDTH/8); byte_index++) begin
                            if (wstrb[byte_index]) begin
                                slv_reg13[(byte_index*8) +: 8] <= wdata[(byte_index*8) +: 8];
                            end
                        end
                    end
                    4'b1110: begin
                        int byte_index; // procedural loop variable
                        for (byte_index = 0; byte_index < (DATA_WIDTH/8); byte_index++) begin
                            if (wstrb[byte_index]) begin
                                slv_reg14[(byte_index*8) +: 8] <= wdata[(byte_index*8) +: 8];
                            end
                        end
                    end
                    4'b1111: begin
                        int byte_index; // procedural loop variable
                        for (byte_index = 0; byte_index < (DATA_WIDTH/8); byte_index++) begin
                            if (wstrb[byte_index]) begin
                                slv_reg15[(byte_index*8) +: 8] <= wdata[(byte_index*8) +: 8];
                            end
                        end
                    end
                    default: begin
                        slv_reg0 <= slv_reg0;
                        slv_reg1 <= slv_reg1;
                        slv_reg2 <= slv_reg2;
                        slv_reg3 <= slv_reg3;
                        slv_reg4 <= slv_reg4;
                        slv_reg5 <= slv_reg5;
                        slv_reg6 <= slv_reg6;
                        slv_reg7 <= slv_reg7;
                        slv_reg8 <= slv_reg8;
                        slv_reg9 <= slv_reg9;
                        slv_reg10 <= slv_reg10;
                        slv_reg11 <= slv_reg11;
                        slv_reg12 <= slv_reg12;
                        slv_reg13 <= slv_reg13;
                        slv_reg14 <= slv_reg14;
                        slv_reg15 <= slv_reg15;
			end
                endcase
        end
        end
    end


    // Write Response
    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            axi_bvalid <= 1'b0;
            axi_bresp  <= 2'b00;
        end else begin
            if (axi_awready && awvalid && axi_wready && wvalid && !axi_bvalid) begin
                axi_bvalid <= 1'b1;
                axi_bresp  <= 2'b00; // OKAY
            end else if (bready && axi_bvalid) begin
                axi_bvalid <= 1'b0;
            end
        end
    end

    // Read Address Channel
    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            axi_arready <= 1'b0;
            axi_araddr  <= '1;
        end else if (!axi_arready && arvalid) begin
            axi_arready <= 1'b1;
            axi_araddr  <= araddr;
        end else begin
            axi_arready <= 1'b0;
        end
    end

    // Read valid generation
    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            axi_rvalid <= 1'b0;
            axi_rresp  <= 2'b00;
        end else begin
            if (axi_arready && arvalid && !axi_rvalid) begin
                axi_rvalid <= 1'b1;
                axi_rresp  <= 2'b00;
            end else if (axi_rvalid && rready) begin
                axi_rvalid <= 1'b0;
            end
        end
    end

    assign slv_reg_rden = axi_arready && arvalid && !axi_rvalid;

    // Read mux
    always_comb begin
  logic [3:0] loc_addr;
  loc_addr = axi_araddr[ADDR_LSB + OPT_MEM_ADDR_BITS : ADDR_LSB];

  case (loc_addr)
    4'h0: reg_data_out = slv_reg0;
    4'h1: reg_data_out = slv_reg1;
    4'h2: reg_data_out = slv_reg2;
    4'h3: reg_data_out = slv_reg3;
    4'h4: reg_data_out = slv_reg4;
    4'h5: reg_data_out = slv_reg5;
    4'h6: reg_data_out = slv_reg6;
    4'h7: reg_data_out = slv_reg7;
    4'h8: reg_data_out = slv_reg8;
    4'h9: reg_data_out = slv_reg9;
    4'hA: reg_data_out = slv_reg10;
    4'hB: reg_data_out = slv_reg11;
    4'hC: reg_data_out = slv_reg12;
    4'hD: reg_data_out = slv_reg13;
    4'hE: reg_data_out = slv_reg14;
    4'hF: reg_data_out = slv_reg15;
    default: reg_data_out = '0;
  endcase
end


    // Output read data
    always_ff @(posedge aclk) begin
        if (!aresetn)
            axi_rdata <= '0;
        else if (slv_reg_rden)
            axi_rdata <= reg_data_out;
    end

    // Register Map Assignments
    assign AVG_START_REG        = slv_reg0[0];
    assign AVG_ADDR_REG         = slv_reg1;
    assign AVG_LEN_REG          = slv_reg2;
    assign AVG_DR_START_REG     = slv_reg3[0];
    assign AVG_DR_ADDR_REG      = slv_reg4;
    assign AVG_DR_LEN_REG       = slv_reg5;
    assign BUF_START_REG        = slv_reg6[0];
    assign BUF_ADDR_REG         = slv_reg7;
    assign BUF_LEN_REG          = slv_reg8;
    assign BUF_DR_START_REG     = slv_reg9[0];
    assign BUF_DR_ADDR_REG      = slv_reg10;
    assign BUF_DR_LEN_REG       = slv_reg11;
    assign AVG_PHOTON_MODE_REG  = slv_reg12[0];
    assign AVG_H_THRSH_REG      = slv_reg13;
    assign AVG_L_THRSH_REG      = slv_reg14;

endmodule