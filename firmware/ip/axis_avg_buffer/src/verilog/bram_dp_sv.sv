module bram_dp_sv #(
    parameter int N = 16,
    parameter int B = 16
)(
    input  logic             clka,
    input  logic             clkb,
    input  logic             ena,
    input  logic             enb,
    input  logic             wea,
    input  logic             web,
    input  logic [N-1:0]     addra,
    input  logic [N-1:0]     addrb,
    input  logic [B-1:0]     dia,
    input  logic [B-1:0]     dib,
    output logic [B-1:0]     doa,
    output logic [B-1:0]     dob
);

    // RAM declaration (equivalent to shared variable)
    logic [B-1:0] RAM [0:(1<<N)-1];

    // CLKA port
    always_ff @(posedge clka) begin
        if (ena) begin
            doa <= RAM[addra];
            if (wea) begin
                RAM[addra] <= dia;
            end
        end
    end

    // CLKB port
    always_ff @(posedge clkb) begin
        if (enb) begin
            dob <= RAM[addrb];
            if (web) begin
                RAM[addrb] <= dib;
            end
        end
    end

endmodule