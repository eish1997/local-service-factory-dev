using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Text;

class SfxLauncher
{
    private static readonly byte[] Marker = Encoding.ASCII.GetBytes("ROAD_RESCUE_DASHBOARD_ZIP_V1");

    static int Main()
    {
        try
        {
            string self = Process.GetCurrentProcess().MainModule.FileName;
            byte[] payload = ReadPayload(self);
            string extractRoot = Path.Combine(Path.GetTempPath(), "RoadRescueDashboard-" + Hash(payload).Substring(0, 12));
            string exePath = Path.Combine(extractRoot, "RoadRescueDashboard.exe");

            if (!File.Exists(exePath))
            {
                if (Directory.Exists(extractRoot)) Directory.Delete(extractRoot, true);
                Directory.CreateDirectory(extractRoot);
                using (MemoryStream stream = new MemoryStream(payload))
                using (ZipArchive archive = new ZipArchive(stream, ZipArchiveMode.Read))
                {
                    archive.ExtractToDirectory(extractRoot);
                }
            }

            ProcessStartInfo startInfo = new ProcessStartInfo(exePath);
            startInfo.WorkingDirectory = extractRoot;
            startInfo.UseShellExecute = false;
            string projectRoot = FindProjectRoot(Path.GetDirectoryName(self));
            if (!String.IsNullOrEmpty(projectRoot))
            {
                startInfo.EnvironmentVariables["ROAD_RESCUE_FACTORY_HOME"] = projectRoot;
            }
            Process.Start(startInfo);
            return 0;
        }
        catch (Exception ex)
        {
            File.WriteAllText(Path.Combine(Path.GetTempPath(), "RoadRescueDashboard-sfx-error.txt"), ex.ToString());
            return 1;
        }
    }

    private static byte[] ReadPayload(string self)
    {
        byte[] all = File.ReadAllBytes(self);
        int markerStart = all.Length - Marker.Length;
        if (markerStart < 8 || !Marker.SequenceEqual(all.Skip(markerStart).Take(Marker.Length)))
        {
            throw new InvalidDataException("Packaged zip marker was not found.");
        }
        long length = BitConverter.ToInt64(all, markerStart - 8);
        long payloadStart = markerStart - 8 - length;
        if (length <= 0 || payloadStart < 0) throw new InvalidDataException("Packaged zip length is invalid.");
        byte[] payload = new byte[length];
        Buffer.BlockCopy(all, (int)payloadStart, payload, 0, (int)length);
        return payload;
    }

    private static string FindProjectRoot(string start)
    {
        string current = start;
        for (int depth = 0; depth < 4 && !String.IsNullOrEmpty(current); depth++)
        {
            if (File.Exists(Path.Combine(current, "factory.py"))) return current;
            current = Directory.GetParent(current) == null ? null : Directory.GetParent(current).FullName;
        }
        return "";
    }

    private static string Hash(byte[] data)
    {
        using (var sha = System.Security.Cryptography.SHA256.Create())
        {
            return BitConverter.ToString(sha.ComputeHash(data)).Replace("-", "").ToLowerInvariant();
        }
    }
}
