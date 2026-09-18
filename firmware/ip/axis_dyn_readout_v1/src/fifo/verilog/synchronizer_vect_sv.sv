module synchronizer_vect_sv #(parameter N = 2, parameter B = 8)
    (   input logic rstn, clk,
        input logic [B-1:0] data_in,
        output logic [B-1:0] data_out);

    // Internal register
    //(* async_reg = "true" *) 
    logic [B-1:0] data_int_reg [0:N-1];
    
    integer i;

    always_ff @(posedge clk) begin
        if (!rstn) begin
            for (i = 0; i < N; i = i + 1)
                data_int_reg[i] <= '0;
        end else begin
            data_int_reg[0] <= data_in;
            for (i = 1; i < N ; i = i + 1)
                data_int_reg[i] <= data_int_reg[i-1];
        end
    end

    assign data_out = data_int_reg[N-1];
endmodule