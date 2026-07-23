function buildScenario(conid, config)
% buildScenario.m
% Build two-satellite rendezvous scenario in STK using Connect API
%
% Orbit source modes (config.orbitSource):
%   'manual' - create satellites from Keplerian elements (stkSetPropClassical)
%   'excel'  - load instantaneous elements from Excel, convert to ECI,
%              and load as external ephemeris (stkSetEphemerisCBI)
%
% Input:
%   conid  - STK Connect connection ID (from initSTK)
%   config - scenario configuration struct (from scenario_config)

fprintf('\n========== Building STK Scenario ==========\n');

%% 1. Create scenario
fprintf('[01] Creating scenario: %s\n', config.scenarioName);
try
    stkNewObj('/', 'Scenario', config.scenarioName);
    objNames = stkObjNames();
    fprintf('  Scenario created, objects: %s\n', strjoin(objNames, ', '));
catch ME
    fprintf(2, '  FAILED: %s\n', ME.message);
    rethrow(ME);
end

%% 2. Set scenario time
fprintf('[02] Setting time period...\n');
fprintf('  Start: %s\n', config.startTime);
fprintf('  Stop:  %s\n', config.stopTime);
try
    stkSetTimePeriod(config.startTime, config.stopTime, 'GREGUTC');
    stkSetEpoch(config.startTime, 'GREGUTC');
    stkSyncEpoch;
    fprintf('  Time set (duration %.0f sec)\n', config.durationSec);
catch ME
    fprintf(2, '  FAILED: %s\n', ME.message);
    rethrow(ME);
end

%% 3. Create satellites (orbit source dependent)
satAPath = ['*/Satellite/' config.satA.name];
satBPath = ['*/Satellite/' config.satB.name];

if strcmp(config.orbitSource, 'excel')
    %% 3a. Excel mode: load instantaneous elements -> external ephemeris
    fprintf('[03] Loading orbit data from Excel...\n');
    projectRoot = fileparts(fileparts(fileparts(mfilename('fullpath'))));
    excelPath = fullfile(projectRoot, config.orbitExcelFile);
    if ~exist(excelPath, 'file')
        error('Excel orbit file not found: %s', excelPath);
    end

    [timeVec, posA, velA, posB, velB, distKm] = stk_helpers.loadOrbitExcel(excelPath);

    % Create satellite objects
    fprintf('[04] Creating satellites and loading ephemeris...\n');
    stkNewObj('*/', 'Satellite', config.satA.name);
    stkNewObj('*/', 'Satellite', config.satB.name);

    ephemDir = fullfile(projectRoot, config.output.ephemerisDir);
    if ~exist(ephemDir, 'dir')
        mkdir(ephemDir);
    end
    % STK Connect fails to load files from non-ASCII paths (Chinese chars).
    % Write .e files to ASCII temp path for loading; also keep archive copy.
    eFileA = fullfile(tempdir, 'observer_orbit.e');
    eFileB = fullfile(tempdir, 'target_orbit.e');

    % Write .e files and load into STK (auto-switches to StkExternal propagator)
    stkSetEphemerisCBI(satAPath, 'Earth', timeVec, posA, velA, eFileA);
    fprintf('  Observer ephemeris loaded: %d points\n', numel(timeVec));
    stkSetEphemerisCBI(satBPath, 'Earth', timeVec, posB, velB, eFileB);
    fprintf('  Target ephemeris loaded: %d points\n', numel(timeVec));

    % Archive copies into project output dir
    try
        copyfile(eFileA, fullfile(ephemDir, 'observer_orbit.e'));
        copyfile(eFileB, fullfile(ephemDir, 'target_orbit.e'));
    catch
    end

    % Enable orbit display
    try stkConnect(conid, 'Graphics', satAPath, 'Orbit Show On'); catch; end
    try stkConnect(conid, 'Graphics', satBPath, 'Orbit Show On'); catch; end

else
    %% 3b. Manual mode: Keplerian elements
    fprintf('[03] Creating observer: %s\n', config.satA.name);
    try
        stkNewObj('*/', 'Satellite', config.satA.name);
        stkSetPropClassical(satAPath, ...
            config.propagator.name, config.propagator.coordSys, ...
            0, config.durationSec, config.timeStepSec, 0, ...
            config.satA.semiMajorAxis * 1000, ...
            config.satA.eccentricity, ...
            deg2rad(config.satA.inclination), ...
            deg2rad(config.satA.argOfPerigee), ...
            deg2rad(config.satA.RAAN), ...
            deg2rad(config.satA.meanAnomaly), ...
            0);
        stkPropagate(satAPath, 0, config.durationSec);
        try stkConnect(conid, 'Graphics', satAPath, 'Orbit Show On'); catch; end
        fprintf('  Observer: a=%.1f km, e=%.4f, i=%.2f deg\n', ...
            config.satA.semiMajorAxis, config.satA.eccentricity, ...
            config.satA.inclination);
    catch ME
        fprintf(2, '  FAILED: %s\n', ME.message);
        rethrow(ME);
    end

    fprintf('[04] Creating target: %s\n', config.satB.name);
    try
        stkNewObj('*/', 'Satellite', config.satB.name);
        stkSetPropClassical(satBPath, ...
            config.propagator.name, config.propagator.coordSys, ...
            0, config.durationSec, config.timeStepSec, 0, ...
            config.satB.semiMajorAxis * 1000, ...
            config.satB.eccentricity, ...
            deg2rad(config.satB.inclination), ...
            deg2rad(config.satB.argOfPerigee), ...
            deg2rad(config.satB.RAAN), ...
            deg2rad(config.satB.meanAnomaly), ...
            0);
        stkPropagate(satBPath, 0, config.durationSec);
        try stkConnect(conid, 'Graphics', satBPath, 'Orbit Show On'); catch; end
        fprintf('  Target: a=%.1f km, e=%.4f, i=%.2f deg\n', ...
            config.satB.semiMajorAxis, config.satB.eccentricity, ...
            config.satB.inclination);
    catch ME
        fprintf(2, '  FAILED: %s\n', ME.message);
        rethrow(ME);
    end
end

%% 4. Create sensor on observer
fprintf('[05] Creating sensor: %s\n', config.sensor.name);
try
    sensorPath = [satAPath '/Sensor/' config.sensor.name];
    stkNewObj(satAPath, 'Sensor', config.sensor.name);
    % NOTE: sensor pattern must be set manually in STK GUI:
    %   CameraSensor -> Properties -> Basic -> Definition
    %   Sensor Type: EOIR, Field of View: 0.06 deg half-angle
    fprintf('  Sensor created (configure pattern manually in STK GUI)\n');
    fprintf('  Expected: EOIR, half-angle=%.4f deg\n', config.sensor.coneHalfAngle);
catch ME
    fprintf(2, '  FAILED: %s\n', ME.message);
    rethrow(ME);
end

%% 5. Set observer attitude -> track target
fprintf('[06] Setting observer attitude to track target...\n');
try
    targetPath = ['*/Satellite/' config.satB.name];
    attCmd = sprintf('Basic Target "%s"', targetPath);
    stkConnect(conid, 'SetAttitude', satAPath, attCmd);
    fprintf('  Observer (%s) -> Target (%s)\n', config.satA.name, config.satB.name);
catch ME
    fprintf(2, '  Connect command failed: %s\n', ME.message);
    fprintf(2, '  Set attitude manually: ObserverSat -> Properties -> Attitude\n');
    fprintf(2, '    -> Target Pointing -> Select Targets -> %s\n', config.satB.name);
end

%% 6. Reset animation
fprintf('[07] Resetting animation...\n');
try
    stkConnect(conid, 'Animate', 'Reset');
    fprintf('  Done\n');
catch
end

%% 7. Verify inter-satellite distance at key epochs
fprintf('[08] Verifying distances via STK...\n');
try
    checkTimes = [0, floor(config.durationSec/2), config.durationSec];
    labels = {'start', 'mid', 'end'};
    for k = 1:numel(checkTimes)
        t = checkTimes(k);
        [pa, ~] = stkPosVelCBI(satAPath, t);
        [pb, ~] = stkPosVelCBI(satBPath, t);
        d = norm(pa - pb) / 1000;
        fprintf('  t=%7.0f s (%s): distance = %.2f km\n', t, labels{k}, d);
    end
catch ME
    fprintf(2, '  Verification warning: %s\n', ME.message);
end

fprintf('\n========== Scenario Build Complete ==========\n\n');
fprintf('Scenario: %s\n', config.scenarioName);
fprintf('  Observer: %s\n', config.satA.name);
fprintf('    Sensor: %s (FOV %.4f deg)\n', ...
    config.sensor.name, config.sensor.coneHalfAngle * 2);
fprintf('  Target:   %s\n', config.satB.name);

end
