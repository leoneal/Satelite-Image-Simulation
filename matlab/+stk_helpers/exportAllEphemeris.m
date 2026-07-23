function exportAllEphemeris(conid, config)
% exportAllEphemeris.m
% Export satellite ephemeris, attitude (computed from geometry), and sun position
%
% Attitude is computed from position/velocity rather than exported from STK,
% since stkAttitudeCBI relies on unreliable file-based export.
%
% Observer attitude: Z_body points toward target, Y_body along orbit normal
% Target attitude: Z_body points toward Earth center (nadir), Y_body along orbit normal
%
% Output files (in config.output.ephemerisDir):
%   observer_state.csv, target_state.csv, sun_state.csv, aux_data.csv, scene_config.json

fprintf('\n========== Exporting Ephemeris Data ==========\n');

projectRoot = fileparts(fileparts(fileparts(mfilename('fullpath'))));
ephemDir = fullfile(projectRoot, config.output.ephemerisDir);
if ~exist(ephemDir, 'dir')
    mkdir(ephemDir);
end

satAPath = sprintf('*/Satellite/%s', config.satA.name);
satBPath = sprintf('*/Satellite/%s', config.satB.name);
tStart = 0;
tStop = config.durationSec;
dt = config.timeStepSec;

%% 1. Load both satellite ephemeris
fprintf('[1/5] Loading satellite ephemeris...\n');
try
    [timeA, posA, velA, ~] = stkEphemerisCBI(satAPath, dt, tStart, tStop);
    [timeB, posB, velB, ~] = stkEphemerisCBI(satBPath, dt, tStart, tStop);
    numSteps = length(timeA);
    fprintf('  Observer: %d steps, Target: %d steps\n', numSteps, length(timeB));
catch ME
    fprintf(2, '  FAILED: %s\n', ME.message);
    rethrow(ME);
end

%% 2. Compute attitudes and write observer state
fprintf('[2/5] Computing attitudes...\n');
try
    quatsA = zeros(4, numSteps);
    quatsB = zeros(4, numSteps);
    for i = 1:numSteps
        quatsA(:,i) = computePointingQuaternion(posA(:,i), velA(:,i), posB(:,i));
        quatsB(:,i) = computeNadirQuaternion(posB(:,i), velB(:,i));
    end
    fprintf('  Attitudes computed\n');

    writeStateCSV(fullfile(ephemDir, 'observer_state.csv'), ...
        timeA, posA, velA, quatsA);
    writeStateCSV(fullfile(ephemDir, 'target_state.csv'), ...
        timeB, posB, velB, quatsB);
catch ME
    fprintf(2, '  FAILED: %s\n', ME.message);
    rethrow(ME);
end

%% 3. Compute sun position (astronomical algorithm, no STK dependency)
fprintf('[3/5] Computing sun position...\n');
try
    % Scenario epoch: convert startTime to Julian date
    epochDT = datetime(config.startTime, 'InputFormat', ...
        'dd MMM yyyy HH:mm:ss.SSS', 'Locale', 'en_US');
    epochJD = posixtime(epochDT) / 86400 + 2440587.5;
    sunPos = zeros(3, numSteps);
    for i = 1:numSteps
        jd = epochJD + timeA(i) / 86400;
        sunPos(:,i) = computeSunPositionECI(jd);
    end
    fprintf('  Sun: %d time steps (computed analytically)\n', numSteps);
    writeSunCSV(fullfile(ephemDir, 'sun_state.csv'), timeA, sunPos);
catch ME
    fprintf(2, '  Sun data warning: %s\n', ME.message);
end

%% 4. Compute auxiliary data
fprintf('[4/5] Computing auxiliary data...\n');
try
    auxData = zeros(numSteps, 3);  % rel_dist_km, rel_vel_ms, sun_phase_deg
    for i = 1:numSteps
        d = posA(:,i) - posB(:,i);
        auxData(i, 1) = norm(d) / 1000;
        v = velA(:,i) - velB(:,i);
        auxData(i, 2) = norm(v);
        obsToTgt = posB(:,i) - posA(:,i);
        tgtToSun = sunPos(:,i) - posB(:,i);
        auxData(i, 3) = acosd(dot(obsToTgt/norm(obsToTgt), tgtToSun/norm(tgtToSun)));
    end
    writeAuxCSV(fullfile(ephemDir, 'aux_data.csv'), timeA, auxData);
    fprintf('  Aux: dist %.1f-%.1f km, phase %.1f-%.1f deg\n', ...
        min(auxData(:,1)), max(auxData(:,1)), ...
        min(auxData(:,3)), max(auxData(:,3)));
catch ME
    fprintf(2, '  Aux warning: %s\n', ME.message);
end

%% 5. Write scene config
fprintf('[5/5] Writing scene config...\n');
try
    writeSceneConfig(fullfile(ephemDir, 'scene_config.json'), config);
catch ME
    fprintf(2, '  Config warning: %s\n', ME.message);
end

fprintf('\n========== Export Complete ==========\n');
fprintf('Output: %s\n', ephemDir);

end

%% ===== Quaternion computation =====

function q = computePointingQuaternion(obsPos, obsVel, tgtPos)
% Compute quaternion for camera pointing at target
% Z_body = direction from observer to target
% Y_body = orbit normal (pos x vel)
% X_body = Y_body x Z_body
% Returns q = [qx, qy, qz, qw]

    z_body = (tgtPos - obsPos) / norm(tgtPos - obsPos);
    y_body = cross(obsPos, obsVel) / norm(cross(obsPos, obsVel));
    x_body = cross(y_body, z_body);
    x_body = x_body / norm(x_body);
    y_body = cross(z_body, x_body);  % re-orthogonalize

    q = rotationMatrixToQuaternion([x_body, y_body, z_body]);
end

function q = computeNadirQuaternion(pos, vel)
% Compute quaternion for nadir-pointing (Earth-facing)
% Z_body = toward Earth center (opposite of position in ECI)
% Y_body = orbit normal (pos x vel)
% X_body = Y_body x Z_body

    z_body = -pos / norm(pos);
    y_body = cross(pos, vel) / norm(cross(pos, vel));
    x_body = cross(y_body, z_body);
    x_body = x_body / norm(x_body);
    y_body = cross(z_body, x_body);

    q = rotationMatrixToQuaternion([x_body, y_body, z_body]);
end

function q = rotationMatrixToQuaternion(R)
% Convert 3x3 rotation matrix to quaternion [qx, qy, qz, qw]
    qw = 0.5 * sqrt(max(0, 1 + R(1,1) + R(2,2) + R(3,3)));
    if qw > 1e-10
        qx = (R(3,2) - R(2,3)) / (4 * qw);
        qy = (R(1,3) - R(3,1)) / (4 * qw);
        qz = (R(2,1) - R(1,2)) / (4 * qw);
    else
        % Fallback for 180-degree case
        qx = sqrt(max(0, 1 + R(1,1) - R(2,2) - R(3,3))) / 2;
        qy = sqrt(max(0, 1 - R(1,1) + R(2,2) - R(3,3))) / 2;
        qz = sqrt(max(0, 1 - R(1,1) - R(2,2) + R(3,3))) / 2;
        qw = 0;
        [~, idx] = max([qx, qy, qz]);
        if idx == 1, qx = abs(qx) * sign(R(3,2) - R(2,3)); end
        if idx == 2, qy = abs(qy) * sign(R(1,3) - R(3,1)); end
        if idx == 3, qz = abs(qz) * sign(R(2,1) - R(1,2)); end
    end
    q = [qx; qy; qz; qw];
end

%% ===== Sun position computation =====

function sunPos = computeSunPositionECI(jd)
% Compute Sun position in ECI (J2000 equatorial) coordinates
% Input: jd = Julian date
% Output: sunPos = [x; y; z] in meters
%
% Based on Meeus astronomical algorithms (low precision, ~0.01 deg accuracy)

    % Julian centuries from J2000.0
    T = (jd - 2451545.0) / 36525.0;

    % Sun mean longitude (degrees)
    L0 = mod(280.46646 + 36000.76983 * T + 0.0003032 * T^2, 360);

    % Sun mean anomaly (degrees)
    M = mod(357.52911 + 35999.05029 * T - 0.0001537 * T^2, 360);

    % Earth orbit eccentricity
    e = 0.016708634 - 0.000042037 * T - 0.0000001267 * T^2;

    % Sun equation of center
    M_rad = deg2rad(M);
    C = (1.914602 - 0.004817 * T - 0.000014 * T^2) * sin(M_rad) ...
        + (0.019993 - 0.000101 * T) * sin(2 * M_rad) ...
        + 0.000289 * sin(3 * M_rad);

    % Sun true longitude
    Theta = L0 + C;

    % Obliquity of the ecliptic (degrees)
    eps0 = 23.439291 - 0.0130042 * T - 1.64e-7 * T^2 + 5.04e-7 * T^3;

    % Convert to ECI equatorial
    Theta_rad = deg2rad(Theta);
    eps_rad = deg2rad(eps0);

    % Sun distance in AU
    R_AU = 1.000001018 * (1 - e^2) / (1 + e * cos(deg2rad(M + C)));

    % AU to meters
    AU_m = 149597870700;
    R = R_AU * AU_m;

    % Convert ecliptic to equatorial (J2000)
    sunPos = zeros(3,1);
    sunPos(1) = R * cos(Theta_rad);                       % x
    sunPos(2) = R * sin(Theta_rad) * cos(eps_rad);        % y
    sunPos(3) = R * sin(Theta_rad) * sin(eps_rad);        % z
end

%% ===== CSV writers =====

function writeStateCSV(filepath, timeVec, posMat, velMat, quatMat)
    fid = fopen(filepath, 'w');
    fprintf(fid, 'time_epoch_sec,pos_x_m,pos_y_m,pos_z_m,vel_x_ms,vel_y_ms,vel_z_ms,qx,qy,qz,qw\n');
    for i = 1:length(timeVec)
        fprintf(fid, '%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.8f,%.8f,%.8f,%.8f\n', ...
            timeVec(i), ...
            posMat(1,i), posMat(2,i), posMat(3,i), ...
            velMat(1,i), velMat(2,i), velMat(3,i), ...
            quatMat(1,i), quatMat(2,i), quatMat(3,i), quatMat(4,i));
    end
    fclose(fid);
    fprintf('  -> %s (%d rows)\n', filepath, length(timeVec));
end

function writeSunCSV(filepath, timeVec, posMat)
    fid = fopen(filepath, 'w');
    fprintf(fid, 'time_epoch_sec,pos_x_m,pos_y_m,pos_z_m\n');
    for i = 1:length(timeVec)
        fprintf(fid, '%.6f,%.6f,%.6f,%.6f\n', ...
            timeVec(i), posMat(1,i), posMat(2,i), posMat(3,i));
    end
    fclose(fid);
end

function writeAuxCSV(filepath, timeVec, auxMat)
    fid = fopen(filepath, 'w');
    fprintf(fid, 'time_epoch_sec,rel_dist_km,rel_vel_ms,sun_phase_deg\n');
    for i = 1:length(timeVec)
        fprintf(fid, '%.6f,%.6f,%.6f,%.4f\n', ...
            timeVec(i), auxMat(i,1), auxMat(i,2), auxMat(i,3));
    end
    fclose(fid);
end

function writeSceneConfig(filepath, config)
    s = struct();
    s.scenario_name = config.scenarioName;
    s.start_time = config.startTime;
    s.stop_time = config.stopTime;
    s.time_step_sec = config.timeStepSec;
    s.duration_sec = config.durationSec;
    s.num_frames = config.numFrames;
    s.observer_name = config.satA.name;
    s.target_name = config.satB.name;
    s.sensor_fov_deg = config.sensor.coneHalfAngle * 2;
    s.sensor_half_angle_deg = config.sensor.coneHalfAngle;
    s.image_width_px = config.sensor.imageWidth;
    s.image_height_px = config.sensor.imageHeight;
    s.coordinate_system = 'J2000 ECI';
    s.units = 'meters, seconds';
    s.files.observer_state = 'observer_state.csv';
    s.files.target_state = 'target_state.csv';
    s.files.sun_state = 'sun_state.csv';
    s.files.aux_data = 'aux_data.csv';

    jsonStr = jsonencode(s);
    fid = fopen(filepath, 'w');
    fprintf(fid, '%s', jsonStr);
    fclose(fid);
end
