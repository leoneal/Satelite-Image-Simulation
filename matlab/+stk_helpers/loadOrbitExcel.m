function [time, posA, velA, posB, velB, distKm] = loadOrbitExcel(excelFile)
% loadOrbitExcel  Load instantaneous orbital elements from Excel and convert
%                 to ECI Cartesian state vectors for both satellites
%
% Input:
%   excelFile - full path to Excel file with columns:
%     Self_a, Self_e, Self_i, Self_omega, Self_w, Self_f,
%     Tar_a,  Tar_e,  Tar_i,  Tar_omega,  Tar_w,  Tar_f, distance(km)
%     (a in meters, angles in radians, one row per second)
%
% Output:
%   time   - 1xN time vector (sec, starting from 0)
%   posA   - 3xN observer (Self) ECI positions (meters)
%   velA   - 3xN observer ECI velocities (meters/sec)
%   posB   - 3xN target (Tar) ECI positions (meters)
%   velB   - 3xN target ECI velocities (meters/sec)
%   distKm - 1xN inter-satellite distance from Excel column (km)
%
% Handles degenerate rows (e=0, w=0) where the simulator outputs unstable
% omega/f values: detects discontinuities and repairs by interpolation.

fprintf('[loadOrbitExcel] Reading %s ...\n', excelFile);

% Read numeric data (skip header row). readmatrix needs R2019a+;
% fall back to xlsread for older MATLAB (xlsread auto-skips text header).
try
    data = readmatrix(excelFile, 'NumHeaderLines', 1);
catch
    data = xlsread(excelFile);
end
N = size(data, 1);
fprintf('[loadOrbitExcel] %d rows loaded\n', N);

% Pre-allocate
posA = zeros(3, N);
velA = zeros(3, N);
posB = zeros(3, N);
velB = zeros(3, N);
distKm = data(:, 13)';
time = 0:(N-1);

% Convert each row
for i = 1:N
    [posA(:,i), velA(:,i)] = stk_helpers.kepler2cart(...
        data(i,1), data(i,2), data(i,3), data(i,4), data(i,5), data(i,6));
    [posB(:,i), velB(:,i)] = stk_helpers.kepler2cart(...
        data(i,7), data(i,8), data(i,9), data(i,10), data(i,11), data(i,12));
end

% --- Validate against distance column ---
calcDist = sqrt(sum((posA - posB).^2, 1)) / 1000;  % km
err = abs(calcDist - distKm);
badRows = find(err > 1.0);
fprintf('[loadOrbitExcel] Distance check: max_err=%.3f km, bad_rows=%d\n', ...
    max(err), numel(badRows));

% --- Repair bad rows by interpolation from good neighbors ---
if ~isempty(badRows)
    fprintf('[loadOrbitExcel] Repairing %d bad rows (degenerate osculating output)...\n', ...
        numel(badRows));
    goodRows = setdiff(1:N, badRows);
    for k = badRows
        % Find nearest good rows before and after
        prevGood = goodRows(goodRows < k);
        nextGood = goodRows(goodRows > k);
        if isempty(prevGood) && isempty(nextGood)
            error('No good rows available for repair');
        elseif isempty(prevGood)
            % Extrapolate backward from next two good rows
            g1 = nextGood(1);
            if numel(nextGood) >= 2
                g2 = nextGood(2);
                dt = g1 - k;
                posA(:,k) = posA(:,g1) - velA(:,g1)*dt - 0.5*(velA(:,g2)-velA(:,g1))*dt;
                posB(:,k) = posB(:,g1) - velB(:,g1)*dt - 0.5*(velB(:,g2)-velB(:,g1))*dt;
                velA(:,k) = velA(:,g1);
                velB(:,k) = velB(:,g1);
            else
                posA(:,k) = posA(:,g1);
                velA(:,k) = velA(:,g1);
                posB(:,k) = posB(:,g1);
                velB(:,k) = velB(:,g1);
            end
        elseif isempty(nextGood)
            % Extrapolate forward from previous good row
            g1 = prevGood(end);
            dt = k - g1;
            posA(:,k) = posA(:,g1) + velA(:,g1)*dt;
            posB(:,k) = posB(:,g1) + velB(:,g1)*dt;
            velA(:,k) = velA(:,g1);
            velB(:,k) = velB(:,g1);
        else
            % Linear interpolation between bracketing good rows
            g1 = prevGood(end);
            g2 = nextGood(1);
            alpha = (k - g1) / (g2 - g1);
            posA(:,k) = (1-alpha)*posA(:,g1) + alpha*posA(:,g2);
            posB(:,k) = (1-alpha)*posB(:,g1) + alpha*posB(:,g2);
            velA(:,k) = (1-alpha)*velA(:,g1) + alpha*velA(:,g2);
            velB(:,k) = (1-alpha)*velB(:,g1) + alpha*velB(:,g2);
        end
    end
    % Re-check after repair
    calcDist2 = sqrt(sum((posA - posB).^2, 1)) / 1000;
    err2 = abs(calcDist2 - distKm);
    fprintf('[loadOrbitExcel] After repair: max_err=%.3f km\n', max(err2));
end

fprintf('[loadOrbitExcel] Done. Distance range: %.1f - %.1f km\n', ...
    min(distKm), max(distKm));

end
