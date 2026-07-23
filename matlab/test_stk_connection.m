function test_stk_connection()
% test_stk_connection.m
% Test STK 11.6 connection via COM + Connect API

fprintf('\n========== STK 11.6 Connection Test ==========\n');

%% Step 1: Add paths
fprintf('[1/4] Adding STK MATLAB API paths...\n');
stkMatlabPath = 'E:\STK_11.6\bin\Matlab';
stkBinPath = 'E:\STK_11.6\bin';
if ~exist(stkMatlabPath, 'dir')
    error('STK MATLAB API dir not found: %s', stkMatlabPath);
end
addpath(stkMatlabPath);
addpath(stkBinPath);
fprintf('  Done\n');

%% Step 2: Start STK via COM + open Connect + init
fprintf('[2/4] Starting STK and connecting...\n');
try
    app = actxserver('STK11.Application');
    app.Visible = 1;
    conid = stkOpen(stkDefaultHost);
    stkInit;
    fprintf('  Connected (conid = %d)\n', conid);
catch ME
    fprintf(2, '  FAILED: %s\n', ME.message);
    fprintf(2, '  Ensure STK is installed and licensed.\n');
    rethrow(ME);
end

%% Step 3: Create test scenario
fprintf('[3/4] Creating test scenario...\n');
try
    stkNewObj('/', 'Scenario', 'TestConnection');
    stkSetTimePeriod('1 Jul 2026 12:00:00', '1 Jul 2026 13:00:00', 'GREGUTC');
    stkSetEpoch('1 Jul 2026 12:00:00', 'GREGUTC');
    stkSyncEpoch;
    stkNewObj('*/', 'Satellite', 'TestSat');
    objList = stkObjNames();
    fprintf('  Scenario objects: %s\n', strjoin(objList, ', '));
catch ME
    fprintf(2, '  FAILED: %s\n', ME.message);
    rethrow(ME);
end

%% Step 4: Cleanup
fprintf('[4/4] Closing...\n');
try
    stkClose(conid);
catch
end
try
    app.Quit;
catch
end
fprintf('  Done\n');

fprintf('\n========================================\n');
fprintf('  STK Connection Test PASSED!\n');
fprintf('========================================\n\n');

end
