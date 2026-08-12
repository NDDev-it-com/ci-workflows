// Smallest program that still asserts something, so the run lane can fail on
// behaviour rather than on the binary merely existing.
static int Checksum(string text)
{
    var total = 0;
    foreach (var b in System.Text.Encoding.UTF8.GetBytes(text))
    {
        total += b;
    }
    return total % 256;
}

if (Checksum("ci") != 204 || Checksum("") != 0)
{
    Console.Error.WriteLine("checksum fixture failed");
    return 1;
}

Console.WriteLine("checksum fixture ok");
return 0;
