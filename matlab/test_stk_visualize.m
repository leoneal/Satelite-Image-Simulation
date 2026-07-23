function test_stk_visualize()
% test_stk_visualize.m
% Diagnose why script-created satellites don't display in STK 2D/3D windows.
% Compares VO (visual object) properties of script-created vs auto STK behavior.
%
% Run after: main.m (rebuilds scenario via Connect API)

fprintf('\n========== STK Satellite Visibility Diagnostic ==========\n');

% Get STK objects from base workspace (exported by main.m)
app = evalin('base', 'app');
conid = evalin('base', 'conid');

root = app.Personality2;
scenario = root.CurrentScenario;

%% 1. List all objects in the current scenario
fprintf('\n--- Scenario Objects ---\n');
children = scenario.Children;
childCount = children.Count;
fprintf('  Children count: %d\n', childCount);

for i = 0:(childCount-1)
    child = children.Item(int32(i));
    fprintf('  [%d] %s (class: %s)\n', i, char(child.InstanceName), char(child.ClassName));
end

%% 2. Get ObserverSat handle and inspect VO by trial
fprintf('\n--- ObserverSat VO Diagnostic ---\n');
sat = children.Item(int32(0));  % first child (ObserverSat created first)
fprintf('  Satellite: %s\n', char(sat.InstanceName));

% Try accessing VO.Orbit via get()
try
    vo = sat.VO;
    fprintf('  get(sat,''VO'') success, type: %s\n', class(vo));
catch ME
    fprintf('  get(sat,''VO'') failed: %s\n', ME.message);
end

% Try using .VO directly (works for some properties)
try
    orbitColl = sat.VO.Orbit;
    fprintf('  sat.VO.Orbit: %s\n', class(orbitColl));
catch ME
    fprintf('  sat.VO.Orbit failed: %s\n', ME.message);
end

%% 3. Try stkExec for graphics commands
fprintf('\n--- Graphics Connect test ---\n');
satPath = '*/Satellite/ObserverSat';
cmds = {'Graphics %s Orbit Show On', 'Graphics %s PassOrbit Show On'};
for j = 1:length(cmds)
    cmd = sprintf(cmds{j}, satPath);
    try
        stkExec(conid, cmd);
        fprintf('  OK: %s\n', cmd);
    catch ME
        fprintf('  FAIL: %s -> %s\n', cmd, ME.message);
    end
end

%% 4. Summary
fprintf('\n--- Summary ---\n');
fprintf('Data export unaffected. Configure sensor & attitude manually in STK GUI.\n');
fprintf('==============================================================\n\n');

end
