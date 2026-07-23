addpath('E:\STK_11.6\bin\Matlab');
addpath('E:\STK_11.6\bin');

% 用 COM 直接启动 STK（绕过 TCP Connect 连接池限制）
app = actxserver('STK11.Application');
app.Visible = 1;

% STK 此时已在运行，再用 Connect 连接
stkInit;
conid = stkOpen(stkDefaultHost);