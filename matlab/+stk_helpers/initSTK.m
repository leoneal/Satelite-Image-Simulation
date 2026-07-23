function [conid, app] = initSTK(showUI)
% initSTK.m
% Initialize STK 11.6: COM to start STK, then Connect API for scenario building
%
% Strategy: COM provides stable STK startup. Connect API provides known-good
% functions (stkNewObj, stkSetPropClassical, etc.) for scenario construction.
%
% Input:
%   showUI - true (default) to show STK window
%
% Output:
%   conid - STK Connect connection ID
%   app   - STK COM application object (for cleanup: app.Quit)
%
% Usage:
%   [conid, app] = initSTK(true);

if nargin < 1
    showUI = true;
end

%% 1. Add STK paths
stkMatlabPath = 'E:\STK_11.6\bin\Matlab';
stkBinPath = 'E:\STK_11.6\bin';

if ~exist(stkMatlabPath, 'dir')
    error('STK MATLAB API dir not found: %s', stkMatlabPath);
end
if isempty(which('stkOpen'))
    addpath(stkMatlabPath);
    addpath(stkBinPath);
end

%% 2. Start or connect to STK via COM
fprintf('[initSTK] Connecting to STK via COM...\n');
try
    % Try existing instance first, otherwise start new one
    try
        app = actxGetRunningServer('STK11.Application');
        fprintf('[initSTK] Connected to existing STK instance\n');
    catch
        app = actxserver('STK11.Application');
        fprintf('[initSTK] Started new STK instance\n');
    end
    app.Visible = showUI;
    if ~showUI
        app.UserControl = false;
    end
    fprintf('[initSTK] STK COM ready\n');
catch ME
    fprintf(2, '[initSTK] COM startup FAILED: %s\n', ME.message);
    rethrow(ME);
end

%% 3. Open Connect connection (STK is already running via COM)
fprintf('[initSTK] Opening Connect...\n');
try
    conid = stkOpen(stkDefaultHost);
    fprintf('[initSTK] Connect opened (conid = %d)\n', conid);
catch ME
    fprintf(2, '[initSTK] Connect open FAILED: %s\n', ME.message);
    rethrow(ME);
end

%% 4. Initialize Connect commands (optional, may fail on unstable connection)
fprintf('[initSTK] Initializing Connect commands...\n');
try
    stkInit;
    fprintf('[initSTK] Connect commands ready\n');
catch ME
    fprintf('[initSTK] stkInit skipped (Connect may still work): %s\n', ME.message);
    % Don't rethrow - stkInit is not strictly required, individual
    % Connect commands (stkNewObj, stkSetPropClassical, etc.) may
    % still function correctly without it.
end

fprintf('[initSTK] Initialization complete.\n\n');

end
