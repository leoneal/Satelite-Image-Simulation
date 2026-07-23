function config = scenario_config()
% scenario_config.m
% ===================
% Satellite Image Simulation - User Configuration
%
% Orbit source modes:
%   'manual' - use Keplerian elements filled in below (satA/satB)
%   'excel'  - load instantaneous elements from Excel orbit data file
%              (34201 rows, 1 sec/row, covers full rendezvous scenario)
%
% IMPORTANT units for manual mode:
%   Distance: km   Angle: deg   Time: seconds
% ===================

%% ===== Orbit Source Selection =====
config.orbitSource = 'excel';                          % 'excel' or 'manual'
config.orbitExcelFile = 'orbit_data.xlsx';             % relative to project root

%% ===== Scenario Time =====
% Excel orbit data: 34201 rows @ 1 sec/row = 34200 sec = 9.5 hours
config.scenarioName = 'SatelliteRendezvous';
config.startTime    = '1 Jul 2026 12:00:00.000';       % UTC start
config.stopTime     = '1 Jul 2026 21:30:00.000';       % UTC stop (9.5 hours)
config.timeStepSec  = 1.0;                             % time step (sec)

%% ===== Satellite Names =====
config.satA = struct();
config.satA.name = 'ObserverSat';
config.satB = struct();
config.satB.name = 'TargetSat';

%% ===== Manual Mode Orbital Elements (ignored in excel mode) =====
% Observer satellite
config.satA.semiMajorAxis  = 42165.55;   % km
config.satA.eccentricity   = 0.0049;
config.satA.inclination    = 2.58;       % deg
config.satA.RAAN           = 14.82;      % deg
config.satA.argOfPerigee   = 355.82;     % deg
config.satA.meanAnomaly    = 142.98;     % deg
% Target satellite
config.satB.semiMajorAxis  = 42165.55;
config.satB.eccentricity   = 0.0049;
config.satB.inclination    = 2.58;
config.satB.RAAN           = 14.82;
config.satB.argOfPerigee   = 355.82;
config.satB.meanAnomaly    = 143.16;

%% ===== Target Satellite Attitude =====
config.satB.attitudeType = 'NadirECFVel';

%% ===== Sensor / Imaging Payload =====
config.sensor = struct();
config.sensor.name         = 'CameraSensor';
config.sensor.coneHalfAngle = 0.0585;    % cone half-angle (deg), ~0.117 deg FOV
config.sensor.imageWidth   = 2048;
config.sensor.imageHeight  = 2048;

%% ===== Propagator Settings (manual mode only) =====
config.propagator = struct();
config.propagator.name = 'J4Perturbation';
config.propagator.coordSys = 'J2000';

%% ===== Output Settings =====
config.output = struct();
config.output.ephemerisDir = 'output/ephemeris';
config.output.reportDir    = 'output/access_reports';
config.output.imageDir     = 'output/images';

%% ===== Validate =====
config = validateConfig(config);

fprintf('Configuration loaded.\n');
fprintf('  Orbit source: %s\n', config.orbitSource);
fprintf('  Observer: %s\n', config.satA.name);
fprintf('  Target:   %s\n', config.satB.name);
fprintf('  Time:     %s -> %s\n', config.startTime, config.stopTime);
fprintf('  Step:     %.1f sec\n', config.timeStepSec);
fprintf('  Frames:   %d\n', config.numFrames);
fprintf('  FOV:      %.4f deg (half-angle %.4f deg)\n', ...
    config.sensor.coneHalfAngle * 2, config.sensor.coneHalfAngle);

end

%% ===== Internal: Validation =====
function config = validateConfig(config)
    startSec = posixtime(datetime(config.startTime, 'InputFormat', ...
        'dd MMM yyyy HH:mm:ss.SSS', 'Locale', 'en_US'));
    stopSec  = posixtime(datetime(config.stopTime, 'InputFormat', ...
        'dd MMM yyyy HH:mm:ss.SSS', 'Locale', 'en_US'));
    config.durationSec = stopSec - startSec;
    config.numFrames = floor(config.durationSec / config.timeStepSec) + 1;

    if ~ismember(config.orbitSource, {'excel', 'manual'})
        error('config.orbitSource must be ''excel'' or ''manual''');
    end

    if strcmp(config.orbitSource, 'manual')
        fields = {'semiMajorAxis', 'eccentricity', 'inclination', ...
                  'RAAN', 'argOfPerigee', 'meanAnomaly'};
        for f = fields
            if ~isfield(config.satA, f{1})
                error('config.satA missing field: %s', f{1});
            end
            if ~isfield(config.satB, f{1})
                error('config.satB missing field: %s', f{1});
            end
        end
    end

    if config.sensor.coneHalfAngle <= 0 || config.sensor.coneHalfAngle > 90
        error('Sensor cone half-angle must be in (0, 90]');
    end
end
