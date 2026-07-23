function main()
% main.m
% Satellite Image Simulation - Main Entry Script
%
% Uses: COM to start STK + Connect API for scenario building
%
% Usage:
%   1. Edit config/scenario_config.m to set orbital elements
%   2. Close any running STK instances first
%   3. In MATLAB: >> main

fprintf('\n');
fprintf('==============================================\n');
fprintf('  Satellite Image Simulation Pipeline         \n');
fprintf('==============================================\n');
fprintf('\n');

%% Step 0: Load config
fprintf('========== [0/4] Loading Config ==========\n');
try
    projectRoot = fileparts(fileparts(mfilename('fullpath')));
    cd(projectRoot);
    addpath(fullfile(projectRoot, 'config'));
    addpath(fullfile(projectRoot, 'matlab'));

    config = scenario_config();
    fprintf('Config loaded: %d frames\n', config.numFrames);
catch ME
    fprintf(2, 'Config load failed: %s\n', ME.message);
    rethrow(ME);
end

%% Step 1: Init STK (COM startup + Connect API)
fprintf('\n========== [1/4] Init STK ==========\n');
[conid, app] = stk_helpers.initSTK(true);

%% Step 2: Build scenario (Connect API)
fprintf('\n========== [2/4] Build Scenario ==========\n');
try
    stk_helpers.buildScenario(conid, config);
catch ME
    fprintf(2, 'Build failed: %s\n', ME.message);
    try app.Quit; catch; end
    rethrow(ME);
end

%% Step 3: Export ephemeris data
fprintf('\n========== [3/5] Export Data ==========\n');
try
    stk_helpers.exportAllEphemeris(conid, config);
catch ME
    fprintf(2, 'Export failed: %s\n', ME.message);
    fprintf(2, '(You can still check STK visualization manually)\n');
end

%% Step 4: Visual check reminder
fprintf('\n========== [4/5] Visual Verification ==========\n');
fprintf('\nIn STK 3D window:\n');
fprintf('  Right-click CameraSensor -> Sensor -> View From Sensor\n');
fprintf('  Use animation controls to step through time\n');
fprintf('  Verify the target satellite is visible in the FOV\n\n');

%% Step 5: Summary
fprintf('========== [5/5] Complete ==========\n');
fprintf('\nScenario ready!\n');
fprintf('  Scenario: %s\n', config.scenarioName);
fprintf('  Observer: %s (Sensor: %s, FOV: %.4f deg)\n', ...
    config.satA.name, config.sensor.name, config.sensor.coneHalfAngle * 2);
fprintf('  Target:   %s\n', config.satB.name);
fprintf('  Time:     %s -> %s (%d frames)\n', ...
    config.startTime, config.stopTime, config.numFrames);
% Export variables to base workspace
assignin('base', 'app', app);
assignin('base', 'conid', conid);
assignin('base', 'config', config);
fprintf('\n--- Done ---\n');
fprintf('Data exported to: output/ephemeris/\n');
fprintf('STK stays open. Close manually or run: app.Quit\n\n');

end
