
// Program.cs
using System;
using System.IO;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using HtmlAgilityPack;

class Program
{
    static async Task<int> Main(string[] args)
    {
        // Enable support for CP949/EUC-KR encoding
        Encoding.RegisterProvider(System.Text.CodePagesEncodingProvider.Instance);

        // Lotto result page URL
        const string mainUrl = "https://www.dhlottery.co.kr/gameResult.do?method=byWin";
        const string remoteResultsUrl = "https://guitarzoa.github.io/LottoCrawling/page/allLottoResults.json";
        const string outFile = "allLottoResults.json";

        using var httpClient = new HttpClient();
        try
        {
            // 1. Scrape lastGame from HTML meta tag without relying on ContentType charset
            using var responseMain = await httpClient.GetAsync(mainUrl);
            byte[] htmlBytes = await responseMain.Content.ReadAsByteArrayAsync();
            Encoding cp949 = Encoding.GetEncoding(949);  // CP949 alias for EUC-KR
            string html = cp949.GetString(htmlBytes);

            var doc = new HtmlDocument();
            doc.LoadHtml(html);
            var meta = doc.DocumentNode.SelectSingleNode("//meta[@id='desc' and @name='description']");
            if (meta == null)
            {
                Console.Error.WriteLine("❌ meta#desc[name='description'] not found.");
            }
            string content = meta.GetAttributeValue("content", string.Empty);
            int start = content.IndexOf(' ') + 1;
            int end = content.IndexOf('회');
            if (start <= 0 || end <= start)
            {
                Console.Error.WriteLine("❌ Failed to parse lastGame from description content.");
            }
            if (!int.TryParse(content[start..end], out int lastGame))
            {
                Console.Error.WriteLine($"❌ Invalid number '{content[start..end]}'");
            }
            Console.WriteLine($"Latest draw (lastGame): {lastGame}");

            // 2. Prepare existing results and determine resume point
            JsonArray results = null;
            int startDrwNo = 1;
            try
            {
                using var resp = await httpClient.GetAsync(remoteResultsUrl);
                if (resp.IsSuccessStatusCode)
                {
                    var jsonBytes = await resp.Content.ReadAsByteArrayAsync();
                    string remoteJson = Encoding.UTF8.GetString(jsonBytes).TrimStart('\uFEFF');
                    if (JsonNode.Parse(remoteJson) is JsonArray remoteArr)
                    {
                        results = remoteArr;
                        startDrwNo = remoteArr.Select(n => n?["drwNo"]?.GetValue<int>() ?? 0).DefaultIfEmpty(0).Max() + 1;
                        Console.WriteLine($"Resuming from remote, next draw: {startDrwNo}");
                    }
                }
            }
            catch { /* ignore remote errors */ }


            // 3. Fetch remaining draws
            if (results != null)
            {
                for (int drwNo = startDrwNo; drwNo <= lastGame; drwNo++)
                {
                    string apiUrl = $"https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo={drwNo}";
                    try
                    {
                        // Ensure UTF8 decoding
                        using var resp = await httpClient.GetAsync(apiUrl);
                        var bytes = await resp.Content.ReadAsByteArrayAsync();
                        string json = Encoding.UTF8.GetString(bytes);
                        if (JsonNode.Parse(json) is JsonNode node)
                        {
                            results.Add(node);
                            Console.WriteLine($"Fetched draw {drwNo}/{lastGame}");
                        }
                    }
                    catch (Exception ex)
                    {
                        Console.Error.WriteLine($"⚠️ Error fetching draw {drwNo}: {ex.Message}");
                    }
                    await Task.Delay(50);
                }

                // 4. Write all results back
                string combined = results.ToJsonString(new JsonSerializerOptions { WriteIndented = true });
                await File.WriteAllTextAsync(outFile, combined, Encoding.UTF8);

                if (startDrwNo > lastGame)
                {
                    Console.WriteLine($"No new draws. Up to {lastGame}.");
                }
                else
                {
                    Console.WriteLine($"{outFile} updated");
                }

            }

            return 0;

        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"❌ Unexpected error: {ex.Message}");
            return 1;
        }
    }

}
